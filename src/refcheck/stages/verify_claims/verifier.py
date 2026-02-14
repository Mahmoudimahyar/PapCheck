"""LLM-powered claim verification with tiered escalation (V1+V2+V3)."""

import asyncio
import logging
import os

from refcheck.llm.client import LLMResponseInvalidError, call_llm
from refcheck.llm.concurrency import get_llm_semaphore
from refcheck.models.claim import Claim
from refcheck.models.reference import Reference
from refcheck.models.verification import VerificationResult
from refcheck.stages.verify_claims.evidence_builder import build_evidence_sections
from refcheck.stages.verify_claims.tier2_verifier import verify_tier2
from refcheck.stages.verify_claims.tier3_verifier import verify_tier3
from refcheck.stages.verify_claims.verifier_helpers import (
    SourceCoverage,
    apply_claim_type_behavior,
    apply_quote_validation,
    cannot_verify,
    get_source_text,
)

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "anthropic/claude-sonnet-4-5-20250929"
_TIER2_CONFIDENCE_THRESHOLD = 0.80
_SKIP_TIER2_TYPES = frozenset({"background"})


async def verify_claims(
    claims: list[Claim],
    references: list[Reference],
) -> list[VerificationResult]:
    """Verify all claims against cited references with parallel processing.

    V3: Uses asyncio.gather with a semaphore to process claim-reference
    pairs concurrently while respecting rate limits.
    """
    ref_by_id: dict[int, Reference] = {r.id: r for r in references}
    sem = get_llm_semaphore()

    # Build list of (claim, reference) pairs to verify
    pairs: list[tuple[Claim, Reference]] = []
    for claim in claims:
        for ref_id in claim.reference_ids:
            ref = ref_by_id.get(ref_id)
            if not ref:
                logger.warning("Ref %d not found for claim %d", ref_id, claim.id)
                continue
            pairs.append((claim, ref))

    logger.info("Verifying %d claim-reference pairs in parallel", len(pairs))

    async def _guarded_verify(c: Claim, r: Reference) -> VerificationResult:
        async with sem:
            return await _verify_single(c, r)

    results = await asyncio.gather(
        *[_guarded_verify(c, r) for c, r in pairs],
    )
    result_list = list(results)
    _log_tier_stats(result_list)
    return result_list


async def _verify_single(claim: Claim, ref: Reference) -> VerificationResult:
    """Verify a single claim — Tier 1, then Tier 2 if needed."""
    source_text, coverage, sections, headings = get_source_text(claim, ref)

    if coverage == "no_source":
        return cannot_verify(claim, ref, "No source text available")

    result = await _call_verification_llm(claim, ref, source_text, coverage)
    result = apply_quote_validation(result, source_text)
    result = apply_claim_type_behavior(result, claim)

    # V2: Escalate to Tier 2 if needed
    if _should_escalate_tier2(result, claim):
        result = await verify_tier2(claim, ref, sections, result)
        # V2: Escalate to Tier 3 if Tier 2 still disagrees
        if result.needs_user_review and _tier3_available():
            result = await verify_tier3(claim, ref, sections, result)

    # V2: Build evidence sections with positioned quote highlights
    ev_sections = build_evidence_sections(
        source_sections=sections, source_headings=headings,
        evidence_quotes=result.evidence_quotes,
        source_text=source_text, claim_text=claim.extracted_claim,
    )
    result = result.model_copy(update={"evidence_sections": ev_sections})

    return result


def _tier3_available() -> bool:
    """Check if secondary model API key is available for Tier 3."""
    return bool(os.getenv("OPENAI_API_KEY"))


def _is_error_result(result: VerificationResult) -> bool:
    """Check if cannot_verify came from an LLM error (not missing data)."""
    if result.verdict != "cannot_verify":
        return False
    reason = result.reasoning or ""
    return "error" in reason.lower() or "invalid response" in reason.lower()


def _should_escalate_tier2(result: VerificationResult, claim: Claim) -> bool:
    """Check if Tier 1 result should be escalated to Tier 2.

    Always escalates LLM errors (even for background claims) so the
    system retries with different strategies rather than accepting failure.
    """
    # Always escalate errors — the LLM failed, not the verification
    if _is_error_result(result):
        return True
    if claim.claim_type in _SKIP_TIER2_TYPES:
        return False
    if result.confidence < _TIER2_CONFIDENCE_THRESHOLD:
        return True
    return result.verdict not in ("supported", "cannot_verify")


def _log_tier_stats(results: list[VerificationResult]) -> None:
    """Log counts of results at each tier."""
    t = {1: 0, 2: 0, 3: 0}
    for r in results:
        t[r.tier] = t.get(r.tier, 0) + 1
    review = sum(1 for r in results if r.needs_user_review)
    logger.info(
        "Verified %d: T1=%d T2=%d T3=%d review=%d",
        len(results), t[1], t[2], t[3], review,
    )


async def _call_verification_llm(
    claim: Claim,
    ref: Reference,
    source_text: str,
    coverage: SourceCoverage,
    template: str = "grounded_verification",
    model: str | None = None,
) -> VerificationResult:
    """Call the LLM for grounded verification."""
    authors_str = ", ".join(ref.authors[:3]) if ref.authors else "Unknown"

    variables: dict[str, str] = {
        "claim": claim.extracted_claim,
        "claim_type": claim.claim_type,
        "source_sections": source_text,
        "reference_title": ref.title or "Unknown",
        "reference_authors": authors_str,
    }
    if claim.atomic_claims:
        variables["atoms"] = "|||".join(claim.atomic_claims)

    try:
        llm_model = model or _DEFAULT_MODEL
        result: VerificationResult = await call_llm(
            template=template,
            variables=variables,
            output_model=VerificationResult,
            model=llm_model,
        )
        # Override IDs and coverage with our known values
        return result.model_copy(update={
            "claim_id": claim.id,
            "reference_id": ref.id,
            "source_coverage": coverage,
            "tier": 1,
        })
    except LLMResponseInvalidError:
        logger.warning(
            "LLM returned invalid response for claim %d / ref %d",
            claim.id, ref.id,
        )
        return cannot_verify(claim, ref, "LLM returned invalid response", coverage)
    except Exception:
        logger.exception(
            "Unexpected error verifying claim %d / ref %d",
            claim.id, ref.id,
        )
        return cannot_verify(claim, ref, "Verification error occurred", coverage)
