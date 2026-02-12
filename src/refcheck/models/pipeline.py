"""Pipeline state and event data models."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from refcheck.models.claim import Claim
from refcheck.models.matching import MatchResult
from refcheck.models.reference import ParsedManuscript, Reference
from refcheck.models.verification import VerificationResult


class StageStatus(BaseModel):
    """Status of a single pipeline stage."""

    stage: int
    name: str
    status: Literal[
        "pending", "running", "complete", "error", "needs_input"
    ] = "pending"
    elapsed_seconds: float = 0.0
    progress_current: int = 0
    progress_total: int = 0
    message: str = ""


class PipelineEvent(BaseModel):
    """SSE event shape for real-time progress."""

    stage: int = 0
    status: Literal[
        "running", "complete", "error", "needs_input", "pipeline_complete"
    ] = "running"
    progress: dict[str, int] | None = None
    message: str = ""
    elapsed_seconds: float = 0.0
    intervention: dict[str, str | int] | None = None


class Intervention(BaseModel):
    """A user intervention request from the pipeline."""

    intervention_type: Literal[
        "confirm_match", "upload_pdf", "correct_metadata"
    ]
    reference_id: int
    details: str = ""


class PipelineState(BaseModel):
    """Accumulated state across all pipeline stages."""

    session_id: str
    manuscript: ParsedManuscript | None = None
    references: list[Reference] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    match_results: list[MatchResult] = Field(default_factory=list)
    verification_results: list[VerificationResult] = Field(
        default_factory=list
    )
    interventions: list[Intervention] = Field(default_factory=list)
    current_stage: int = 0
    status: Literal[
        "created", "running", "paused", "complete", "error"
    ] = "created"


class Session(BaseModel):
    """API response for session creation."""

    id: str
    status: Literal[
        "created", "running", "paused", "complete", "error"
    ] = "created"
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )
    manuscript_filename: str = ""
    pdf_count: int = 0
