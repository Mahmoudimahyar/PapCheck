"""LLM-powered claim verification (Tier 1: single-model forced grounding)."""

import logging
from pathlib import Path

from refcheck.llm.client import LLMResponseInvalidError, call_llm
from refcheck.models.claim import Claim
from refcheck.models.reference import Reference
from refcheck.models.verification import VerificationResult
from refcheck.stages.verify_claims.quote_validator import validate_quotes
from refcheck.stages.verify_claims.section_finder import find_relevant_sections

logger = logging.getLogger(__name__)

_CONFIDENCE_PENALTY = 0.2


async def verify_claims(
    claims: list[Claim],
    references: list[Reference],
) -> list[VerificationResult]:
    """Verify all claims against their cited references.

    For each claim-reference pair, finds relevant sections in the PDF,
    calls the LLM for verification, and validates evidence quotes.
    """
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

    logger.info("Verified %d claim-reference pairs", len(results))
    return results


async def _verify_single(claim: Claim, ref: Reference) -> VerificationResult:
    """Verify a single claim against a single reference."""
    source_text, coverage = _get_source_text(claim, ref)

    if coverage == "no_source":
        return _cannot_verify(claim, ref, "No source text available")

    result = await _call_verification_llm(claim, ref, source_text, coverage)
    result = _apply_quote_validation(result, source_text)
    result = _apply_claim_type_behavior(result, claim)
    return result


def _get_source_text(
    claim: Claim, ref: Reference,
) -> tuple[str, str]:
    """Get source text for verification and determine coverage type."""
    if ref.pdf_path and Path(ref.pdf_path).exists():
        sections = find_relevant_sections(claim, Path(ref.pdf_path))
        if sections:
            return "\n\n".join(sections), "relevant_sections"

    # No PDF or no sections found
    return "", "no_source"


async def _call_verification_llm(
    claim: Claim,
    ref: Reference,
    source_text: str,
    coverage: str,
) -> VerificationResult:
    """Call the LLM for grounded verification."""
    authors_str = ", ".join(ref.authors[:3]) if ref.authors else "Unknown"

    try:
        result = await call_llm(
            template="grounded_verification",
            variables={
                "claim": claim.extracted_claim,
                "claim_type": claim.claim_type,
                "source_sections": source_text,
                "reference_title": ref.title or "Unknown",
                "reference_authors": authors_str,
            },
            output_model=VerificationResult,
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
    result: VerificationResult,
    source_text: str,
) -> VerificationResult:
    """Validate evidence quotes and downgrade if hallucinated."""
    if not result.evidence_quotes or not source_text:
        return result

    validations = validate_quotes(result.evidence_quotes, source_text)
    invalid_count = sum(1 for v in validations if not v.found_in_source)

    if invalid_count > 0:
        new_confidence = max(0.0, result.confidence - _CONFIDENCE_PENALTY)
        logger.warning(
            "Claim %d/ref %d: %d/%d evidence quotes failed validation",
            result.claim_id, result.reference_id,
            invalid_count, len(result.evidence_quotes),
        )
        return result.model_copy(update={
            "needs_user_review": True,
            "confidence": new_confidence,
        })

    return result


def _apply_claim_type_behavior(
    result: VerificationResult,
    claim: Claim,
) -> VerificationResult:
    """Apply claim-type-specific post-processing."""
    # Background claims: accept more easily
    if (
        claim.claim_type == "background"
        and result.confidence >= 0.5
        and result.verdict in ("partially_supported", "cannot_verify")
    ):
        return result.model_copy(update={"verdict": "supported"})

    # Contrast claims: flag for extra caution
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
