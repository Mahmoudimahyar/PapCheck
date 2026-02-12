"""Verification result data models for V1 claim verification."""

from typing import Literal

from pydantic import BaseModel, Field

Verdict = Literal[
    "supported",
    "partially_supported",
    "not_supported",
    "contradicted",
    "cannot_verify",
]


class VerificationResult(BaseModel):
    """Result of verifying one claim against its cited source."""

    claim_id: int
    reference_id: int
    verdict: Verdict = "cannot_verify"
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Confidence in the verdict"
    )
    evidence_quotes: list[str] = Field(default_factory=list)
    reasoning: str = ""
    tier: Literal[1, 2, 3] = 1
    source_coverage: Literal[
        "full_text", "abstract_only", "relevant_sections", "no_source"
    ] = "no_source"
    needs_user_review: bool = False
    atomic_results: list["AtomicVerification"] | None = None
    user_override: bool = False
    user_override_reason: str = ""
    original_verdict: Verdict | None = None
    original_confidence: float | None = None


class AtomicVerification(BaseModel):
    """Verification of a single atomic claim (V2)."""

    atom: str = ""
    verified: bool | None = None
    evidence: str | None = None
