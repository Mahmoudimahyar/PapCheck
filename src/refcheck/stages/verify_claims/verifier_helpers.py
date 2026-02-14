"""Helper functions for claim verification post-processing."""

import logging
from pathlib import Path
from typing import Literal

from refcheck.models.claim import Claim
from refcheck.models.reference import Reference
from refcheck.models.verification import VerificationResult
from refcheck.stages.verify_claims.quote_validator import validate_quotes
from refcheck.stages.verify_claims.section_finder import (
    find_relevant_sections_with_headings,
)

SourceCoverage = Literal[
    "full_text", "abstract_only", "relevant_sections", "no_source"
]

logger = logging.getLogger(__name__)

_CONFIDENCE_PENALTY = 0.2


def get_source_text(
    claim: Claim, ref: Reference,
) -> tuple[str, SourceCoverage, list[str], list[str]]:
    """Get source text, coverage type, raw sections, and headings."""
    if ref.pdf_path and Path(ref.pdf_path).exists():
        pairs = find_relevant_sections_with_headings(claim, Path(ref.pdf_path))
        if pairs:
            headings = [h for h, _ in pairs]
            sections = [t for _, t in pairs]
            return "\n\n".join(sections), "relevant_sections", sections, headings
    return "", "no_source", [], []


def apply_quote_validation(
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


def apply_claim_type_behavior(
    result: VerificationResult, claim: Claim,
) -> VerificationResult:
    """Apply claim-type-specific post-processing."""
    if (claim.claim_type == "background" and result.confidence >= 0.5
            and result.verdict in ("partially_supported", "cannot_verify")):
        return result.model_copy(update={"verdict": "supported"})
    if claim.claim_type == "contrast":
        return result.model_copy(update={"needs_user_review": True})
    return result


def cannot_verify(
    claim: Claim,
    ref: Reference,
    reason: str,
    coverage: SourceCoverage = "no_source",
) -> VerificationResult:
    """Create a cannot_verify result with explanation.

    Preserves the actual source_coverage so we can distinguish
    'no PDF available' from 'had source text but LLM call failed'.
    """
    return VerificationResult(
        claim_id=claim.id,
        reference_id=ref.id,
        verdict="cannot_verify",
        confidence=0.0,
        reasoning=reason,
        tier=1,
        source_coverage=coverage,
    )


def validate_tier_quotes(
    result: VerificationResult, source_text: str, penalty: float = 0.15,
) -> VerificationResult:
    """Run post-hoc quote validation on a tier result."""
    if not result.evidence_quotes or not source_text:
        return result
    validations = validate_quotes(result.evidence_quotes, source_text)
    invalid = sum(1 for v in validations if not v.found_in_source)
    if invalid > 0:
        new_conf = max(0.0, result.confidence - penalty)
        return result.model_copy(update={
            "confidence": round(new_conf, 3),
            "needs_user_review": True,
        })
    return result


def dedupe_quotes(a: list[str], b: list[str]) -> list[str]:
    """Merge two quote lists, removing duplicates."""
    seen: set[str] = set()
    result: list[str] = []
    for q in a + b:
        normalized = q.strip().lower()
        if normalized not in seen:
            seen.add(normalized)
            result.append(q)
    return result
