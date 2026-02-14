"""SQLModel database table definitions for persistent storage."""

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class SessionDB(SQLModel, table=True):
    """Database model for verification sessions."""

    __tablename__ = "sessions"

    id: str = Field(primary_key=True)
    status: str = Field(default="created")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    manuscript_filename: str = ""
    pdf_count: int = 0
    manuscript_sections_json: str | None = None
    manuscript_path: str | None = None
    pdf_dir: str | None = None
    report_path: str | None = None
    current_stage: int = 0
    error_message: str | None = None
    total_elapsed_seconds: float = 0.0
    stage_timings_json: str = "{}"


class ReferenceDB(SQLModel, table=True):
    """Database model for references extracted from manuscripts."""

    __tablename__ = "references"

    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="sessions.id", index=True)
    ref_number: int
    raw_text: str = ""
    title: str = ""
    authors_json: str = "[]"
    year: int | None = None
    doi: str | None = None
    journal: str | None = None
    pmid: str | None = None
    volume: str | None = None
    pages: str | None = None
    url: str | None = None
    source_status: str = "pending"
    pdf_path: str | None = None
    pdf_source: str | None = None
    journal_url: str | None = None
    retraction_status: str = "unknown"
    retraction_detail: str = ""
    duplicate_of: int | None = None
    is_supplementary: bool = False


class ClaimDB(SQLModel, table=True):
    """Database model for extracted claims."""

    __tablename__ = "claims"

    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="sessions.id", index=True)
    claim_number: int
    manuscript_text: str = ""
    extracted_claim: str = ""
    claim_type: str = "factual"
    reference_ids_json: str = "[]"
    priority: str = "medium"
    section_heading: str = ""
    atomic_claims_json: str = "[]"
    location_json: str | None = None
    skipped: bool = False


class VerificationDB(SQLModel, table=True):
    """Database model for verification results."""

    __tablename__ = "verifications"

    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="sessions.id", index=True)
    claim_id: int
    reference_id: int
    verdict: str = "cannot_verify"
    confidence: float = 0.0
    evidence_quotes_json: str = "[]"
    reasoning: str = ""
    tier: int = 1
    source_coverage: str = "no_source"
    needs_user_review: bool = False
    user_override: bool = False
    user_override_reason: str = ""
    original_verdict: str | None = None
    original_confidence: float | None = None
    atomic_results_json: str | None = None
    evidence_sections_json: str | None = None


class PipelineEventDB(SQLModel, table=True):
    """Database model for pipeline progress events."""

    __tablename__ = "pipeline_events"

    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="sessions.id", index=True)
    stage: int = 0
    status: str = "running"
    progress_json: str | None = None
    message: str = ""
    elapsed_seconds: float = 0.0
    intervention_json: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
