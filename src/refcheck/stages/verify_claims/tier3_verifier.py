"""Tier 3: Multi-model voting for persistent disagreements."""

import logging
import os

from refcheck.llm.client import LLMResponseInvalidError, call_llm
from refcheck.models.claim import Claim
from refcheck.models.reference import Reference
from refcheck.models.verification import VerificationResult
from refcheck.stages.verify_claims.quote_validator import validate_quotes

logger = logging.getLogger(__name__)

_CONFIDENCE_BOOST = 0.05
_MAX_CONFIDENCE = 1.0
_DEFAULT_SECONDARY = "openai/gpt-4o"


async def verify_tier3(
    claim: Claim,
    reference: Reference,
    source_sections: list[str],
    tier2_result: VerificationResult,
    secondary_model: str | None = None,
) -> VerificationResult:
    """Get a second opinion from a different LLM model.

    Compares the secondary model's verdict with Tier 2 and merges.
    Falls back to Tier 2 result if the secondary model call fails.
    """
    env_model = os.getenv("REFCHECK_SECONDARY_MODEL", _DEFAULT_SECONDARY)
    model: str = secondary_model or env_model or _DEFAULT_SECONDARY
    source_text = "\n\n".join(source_sections)
    authors_str = ", ".join(reference.authors[:3]) if reference.authors else "Unknown"

    variables: dict[str, str] = {
        "claim": claim.extracted_claim,
        "claim_type": claim.claim_type,
        "source_sections": source_text,
        "reference_title": reference.title or "Unknown",
        "reference_authors": authors_str,
    }
    if claim.atomic_claims:
        variables["atoms"] = "|||".join(claim.atomic_claims)

    secondary = await _call_secondary(variables, claim, reference, model)
    if secondary is None:
        return tier2_result.model_copy(update={"needs_user_review": True})

    return _merge_models(tier2_result, secondary, claim, reference, source_text)


async def _call_secondary(
    variables: dict[str, str],
    claim: Claim,
    reference: Reference,
    model: str,
) -> VerificationResult | None:
    """Call the secondary model. Returns None on failure."""
    try:
        result = await call_llm(
            template="grounded_verification",
            variables=variables,
            output_model=VerificationResult,
            model=model,
        )
        return result.model_copy(update={
            "claim_id": claim.id,
            "reference_id": reference.id,
        })
    except (LLMResponseInvalidError, Exception):
        logger.warning(
            "Tier 3 secondary model failed for claim %d / ref %d",
            claim.id, reference.id,
        )
        return None


def _merge_models(
    tier2: VerificationResult,
    secondary: VerificationResult,
    claim: Claim,
    reference: Reference,
    source_text: str,
) -> VerificationResult:
    """Merge Tier 2 result with secondary model result."""
    if tier2.verdict == secondary.verdict:
        return _models_agree(tier2, secondary, claim, reference, source_text)
    return _models_disagree(tier2, secondary, claim, reference, source_text)


def _models_agree(
    tier2: VerificationResult,
    secondary: VerificationResult,
    claim: Claim,
    reference: Reference,
    source_text: str,
) -> VerificationResult:
    """Both models agree — boost confidence."""
    avg = (tier2.confidence + secondary.confidence) / 2
    boosted = min(avg + _CONFIDENCE_BOOST, _MAX_CONFIDENCE)
    reasoning = f"{tier2.reasoning}\n[Secondary model] {secondary.reasoning}"
    quotes = _dedupe(tier2.evidence_quotes, secondary.evidence_quotes)

    result = VerificationResult(
        claim_id=claim.id,
        reference_id=reference.id,
        verdict=tier2.verdict,
        confidence=round(boosted, 3),
        evidence_quotes=quotes,
        reasoning=reasoning,
        tier=3,
        source_coverage=tier2.source_coverage,
        needs_user_review=False,
    )
    return _validate_quotes(result, source_text)


def _models_disagree(
    tier2: VerificationResult,
    secondary: VerificationResult,
    claim: Claim,
    reference: Reference,
    source_text: str,
) -> VerificationResult:
    """Models disagree — flag for human review with both reasonings."""
    avg = (tier2.confidence + secondary.confidence) / 2
    reasoning = (
        f"[Primary → {tier2.verdict}] {tier2.reasoning}\n"
        f"[Secondary → {secondary.verdict}] {secondary.reasoning}"
    )
    quotes = _dedupe(tier2.evidence_quotes, secondary.evidence_quotes)

    result = VerificationResult(
        claim_id=claim.id,
        reference_id=reference.id,
        verdict=tier2.verdict,
        confidence=round(avg, 3),
        evidence_quotes=quotes,
        reasoning=reasoning,
        tier=3,
        source_coverage=tier2.source_coverage,
        needs_user_review=True,
    )
    return _validate_quotes(result, source_text)


def _validate_quotes(
    result: VerificationResult, source_text: str,
) -> VerificationResult:
    """Run post-hoc quote validation."""
    if not result.evidence_quotes or not source_text:
        return result
    validations = validate_quotes(result.evidence_quotes, source_text)
    invalid = sum(1 for v in validations if not v.found_in_source)
    if invalid > 0:
        return result.model_copy(update={
            "confidence": round(max(0.0, result.confidence - 0.1), 3),
        })
    return result


def _dedupe(a: list[str], b: list[str]) -> list[str]:
    """Merge two quote lists, removing duplicates."""
    seen: set[str] = set()
    result: list[str] = []
    for q in a + b:
        key = q.strip().lower()
        if key not in seen:
            seen.add(key)
            result.append(q)
    return result
