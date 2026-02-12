"""Tier 2: Dual-strategy verification for uncertain Tier 1 results."""

import logging

from refcheck.llm.client import LLMResponseInvalidError, call_llm
from refcheck.models.claim import Claim
from refcheck.models.reference import Reference
from refcheck.models.verification import VerificationResult
from refcheck.stages.verify_claims.quote_validator import validate_quotes

logger = logging.getLogger(__name__)

_CONFIDENCE_BOOST = 0.05
_MAX_CONFIDENCE = 1.0

# For factual claims, prefer the strict verdict on disagreement
_CONSERVATIVE_TYPES = frozenset({"factual", "contrast", "methodological"})


async def verify_tier2(
    claim: Claim,
    reference: Reference,
    source_sections: list[str],
    tier1_result: VerificationResult,
) -> VerificationResult:
    """Run dual-strategy verification (strict + generous).

    Returns a Tier 2 result that either confirms or flags disagreement.
    """
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

    strict = await _call_strategy("strict_verification", variables, claim, reference)
    generous = await _call_strategy("generous_verification", variables, claim, reference)

    # If one strategy failed, use the other
    if strict is None and generous is None:
        return tier1_result.model_copy(update={"needs_user_review": True})
    if strict is None:
        return _finalize(generous, claim, reference, source_text)  # type: ignore[arg-type]
    if generous is None:
        return _finalize(strict, claim, reference, source_text)

    return _merge_strategies(strict, generous, claim, reference, source_text)


async def _call_strategy(
    template: str,
    variables: dict[str, str],
    claim: Claim,
    reference: Reference,
) -> VerificationResult | None:
    """Call a single verification strategy. Returns None on failure."""
    try:
        result = await call_llm(
            template=template,
            variables=variables,
            output_model=VerificationResult,
        )
        return result.model_copy(update={
            "claim_id": claim.id,
            "reference_id": reference.id,
        })
    except (LLMResponseInvalidError, Exception):
        logger.warning(
            "Tier 2 %s failed for claim %d / ref %d",
            template, claim.id, reference.id,
        )
        return None


def _merge_strategies(
    strict: VerificationResult,
    generous: VerificationResult,
    claim: Claim,
    reference: Reference,
    source_text: str,
) -> VerificationResult:
    """Merge strict and generous results into a Tier 2 verdict."""
    if strict.verdict == generous.verdict:
        return _strategies_agree(strict, generous, claim, reference, source_text)
    return _strategies_disagree(strict, generous, claim, reference, source_text)


def _strategies_agree(
    strict: VerificationResult,
    generous: VerificationResult,
    claim: Claim,
    reference: Reference,
    source_text: str,
) -> VerificationResult:
    """Both strategies agree — boost confidence."""
    avg_conf = (strict.confidence + generous.confidence) / 2
    boosted = min(avg_conf + _CONFIDENCE_BOOST, _MAX_CONFIDENCE)
    quotes = _dedupe_quotes(strict.evidence_quotes, generous.evidence_quotes)
    reasoning = f"[Strict] {strict.reasoning}\n[Generous] {generous.reasoning}"

    result = VerificationResult(
        claim_id=claim.id,
        reference_id=reference.id,
        verdict=strict.verdict,
        confidence=round(boosted, 3),
        evidence_quotes=quotes,
        reasoning=reasoning,
        tier=2,
        source_coverage=strict.source_coverage,
        needs_user_review=False,
    )
    return _validate_tier2_quotes(result, source_text)


def _strategies_disagree(
    strict: VerificationResult,
    generous: VerificationResult,
    claim: Claim,
    reference: Reference,
    source_text: str,
) -> VerificationResult:
    """Strategies disagree — flag for review, use conservative verdict."""
    chosen_verdict = strict.verdict if claim.claim_type in _CONSERVATIVE_TYPES else generous.verdict

    avg_conf = (strict.confidence + generous.confidence) / 2
    quotes = _dedupe_quotes(strict.evidence_quotes, generous.evidence_quotes)
    reasoning = (
        f"[Strict → {strict.verdict}] {strict.reasoning}\n"
        f"[Generous → {generous.verdict}] {generous.reasoning}"
    )

    result = VerificationResult(
        claim_id=claim.id,
        reference_id=reference.id,
        verdict=chosen_verdict,
        confidence=round(avg_conf, 3),
        evidence_quotes=quotes,
        reasoning=reasoning,
        tier=2,
        source_coverage=strict.source_coverage,
        needs_user_review=True,
    )
    return _validate_tier2_quotes(result, source_text)


def _finalize(
    result: VerificationResult,
    claim: Claim,
    reference: Reference,
    source_text: str,
) -> VerificationResult:
    """Finalize a single-strategy fallback result."""
    updated = result.model_copy(update={
        "claim_id": claim.id,
        "reference_id": reference.id,
        "tier": 2,
    })
    return _validate_tier2_quotes(updated, source_text)


def _validate_tier2_quotes(
    result: VerificationResult, source_text: str,
) -> VerificationResult:
    """Run post-hoc quote validation on Tier 2 result."""
    if not result.evidence_quotes or not source_text:
        return result
    validations = validate_quotes(result.evidence_quotes, source_text)
    invalid = sum(1 for v in validations if not v.found_in_source)
    if invalid > 0:
        new_conf = max(0.0, result.confidence - 0.15)
        return result.model_copy(update={
            "confidence": round(new_conf, 3),
            "needs_user_review": True,
        })
    return result


def _dedupe_quotes(a: list[str], b: list[str]) -> list[str]:
    """Merge two quote lists, removing duplicates."""
    seen: set[str] = set()
    result: list[str] = []
    for q in a + b:
        normalized = q.strip().lower()
        if normalized not in seen:
            seen.add(normalized)
            result.append(q)
    return result
