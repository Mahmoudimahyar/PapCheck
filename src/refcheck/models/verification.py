"""Verification result data models (stub for V1)."""

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
    """Result of verifying one claim against its cited source (V1)."""

    claim_id: int
    reference_id: int
    verdict: Verdict = "cannot_verify"
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Confidence in the verdict"
    )
    evidence_quotes: list[str] = Field(default_factory=list)
    reasoning: str = ""
    tier: int = Field(default=1, description="Verification tier (1=single LLM)")
    source_coverage: Literal[
        "full_text", "abstract_only", "no_source"
    ] = "no_source"
    needs_user_review: bool = False


class AtomicVerification(BaseModel):
    """Verification of a single atomic claim (V2)."""

    atomic_claim_id: int
    verdict: Verdict = "cannot_verify"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_quote: str = ""
    reasoning: str = ""
