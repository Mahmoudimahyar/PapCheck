"""Response schemas for verification results endpoints."""

from pydantic import BaseModel, Field


class OverrideRequest(BaseModel):
    """Request body for verdict override."""

    verdict: str
    reason: str = ""


class ResultsSummary(BaseModel):
    """Summary of verification results."""

    total: int = 0
    supported: int = 0
    partially_supported: int = 0
    not_supported: int = 0
    contradicted: int = 0
    cannot_verify: int = 0


class ClaimDetail(BaseModel):
    """Claim info included in results response."""

    manuscript_text: str = ""
    extracted_claim: str = ""
    claim_type: str = ""
    priority: str = ""


class VoteSummary(BaseModel):
    """Lightweight vote info for result items."""

    model_name: str = ""
    abbreviation: str = ""
    tier: int = 0
    verdict: str = ""
    confidence: float = 0.0


class ResultItem(BaseModel):
    """Single result in the results response."""

    claim_id: int
    reference_id: int
    verdict: str
    confidence: float
    evidence_quotes: list[str] = Field(default_factory=list)
    reasoning: str = ""
    tier: int = 1
    source_coverage: str = "no_source"
    needs_user_review: bool = False
    user_override: bool = False
    user_override_reason: str = ""
    claim: ClaimDetail = Field(default_factory=ClaimDetail)
    # V4: Multi-model voting fields
    consensus_type: str = ""
    final_tier: int = 0
    total_models_consulted: int = 0
    agreement_ratio: float = 0.0


class ResultsResponse(BaseModel):
    """Full paginated results response."""

    summary: ResultsSummary
    results: list[ResultItem]
    total: int
    page: int
    per_page: int
