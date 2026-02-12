"""LLM-powered claim verification with tiered escalation (V1+V2)."""

import logging
import os
from pathlib import Path

from refcheck.llm.client import LLMResponseInvalidError, call_llm
from refcheck.models.claim import Claim
from refcheck.models.reference import Reference
from refcheck.models.verification import VerificationResult
from refcheck.stages.verify_claims.quote_validator import validate_quotes
from refcheck.stages.verify_claims.section_finder import find_relevant_sections
from refcheck.stages.verify_claims.tier2_verifier import verify_tier2
from refcheck.stages.verify_claims.tier3_verifier import verify_tier3

logger = logging.getLogger(__name__)

_CONFIDENCE_PENALTY = 0.2
_DEFAULT_MODEL = "anthropic/claude-sonnet-4-5-20250929"
_TIER2_CONFIDENCE_THRESHOLD = 0.80
_SKIP_TIER2_TYPES = frozenset({"background"})


async def verify_claims(
    claims: list[Claim],
    references: list[Reference],
) -> list[VerificationResult]:
    """Verify all claims against cited references with tiered escalation."""
    ref_by_id: dict[int, Reference] = {r.id: r for r in references}
    results: list[VerificationResult] = []
    for claim in claims:
        for ref_id in claim.reference_ids:
            ref = ref_by_id.get(ref_id)
            if not ref:
                logger.warning("Reference %d not found for claim %d", ref_id, claim.id)
                continue
            result = await _verify_single(claim, ref)
            results.append(result)
    _log_tier_stats(results)
    return results


async def _verify_single(claim: Claim, ref: Reference) -> VerificationResult:
    """Verify a single claim — Tier 1, then Tier 2 if needed."""
    source_text, coverage, sections = _get_source_text(claim, ref)

    if coverage == "no_source":
        return _cannot_verify(claim, ref, "No source text available")

    result = await _call_verification_llm(claim, ref, source_text, coverage)
    result = _apply_quote_validation(result, source_text)
    result = _apply_claim_type_behavior(result, claim)

    # V2: Escalate to Tier 2 if needed
    if _should_escalate_tier2(result, claim):
        result = await verify_tier2(claim, ref, sections, result)
        # V2: Escalate to Tier 3 if Tier 2 still disagrees
        if result.needs_user_review and _tier3_available():
            result = await verify_tier3(claim, ref, sections, result)

    return result


def _get_source_text(
    claim: Claim, ref: Reference,
) -> tuple[str, str, list[str]]:
    """Get source text, coverage type, and raw sections list."""
    if ref.pdf_path and Path(ref.pdf_path).exists():
        sections = find_relevant_sections(claim, Path(ref.pdf_path))
        if sections:
            return "\n\n".join(sections), "relevant_sections", sections
    return "", "no_source", []


def _tier3_available() -> bool:
    """Check if secondary model API key is available for Tier 3."""
    return bool(os.getenv("OPENAI_API_KEY"))


def _should_escalate_tier2(result: VerificationResult, claim: Claim) -> bool:
    """Check if Tier 1 result should be escalated to Tier 2."""
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
    coverage: str,
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
        return _cannot_verify(claim, ref, "LLM returned invalid response")
    except Exception:
        logger.exception(
            "Unexpected error verifying claim %d / ref %d",
            claim.id, ref.id,
        )
        return _cannot_verify(claim, ref, "Verification error occurred")


def _apply_quote_validation(
    result: VerificationResult, source_text: str,
) -> VerificationResult:
    """Validate evidence quotes and downgrade if hallucinated."""
    if not result.evidence_quotes or not source_text:
        return result
    validations = validate_quotes(result.evidence_quotes, source_text)
    invalid_count = sum(1 for v in validations if not v.found_in_source)
    if invalid_count > 0:
        new_conf = max(0.0, result.confidence - _CONFIDENCE_PENALTY)
        logger.warning(
            "Claim %d/ref %d: %d/%d quotes failed validation",
            result.claim_id, result.reference_id,
            invalid_count, len(result.evidence_quotes),
        )
        return result.model_copy(update={
            "needs_user_review": True, "confidence": new_conf,
        })
    return result


def _apply_claim_type_behavior(
    result: VerificationResult, claim: Claim,
) -> VerificationResult:
    """Apply claim-type-specific post-processing."""
    if (claim.claim_type == "background" and result.confidence >= 0.5
            and result.verdict in ("partially_supported", "cannot_verify")):
        return result.model_copy(update={"verdict": "supported"})
    if claim.claim_type == "contrast":
        return result.model_copy(update={"needs_user_review": True})
    return result


def _cannot_verify(
    claim: Claim, ref: Reference, reason: str,
) -> VerificationResult:
    """Create a cannot_verify result with explanation."""
    return VerificationResult(
        claim_id=claim.id,
        reference_id=ref.id,
        verdict="cannot_verify",
        confidence=0.0,
        reasoning=reason,
        tier=1,
        source_coverage="no_source",
    )
