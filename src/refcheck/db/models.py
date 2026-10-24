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
    pmc_id: str | None = None
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
    # V2 fields
    raw_text_original: str = ""
    repair_applied: str = "none"
    reference_type: str = "journal_article"
    abstract_text: str | None = None
    abstract_source: str | None = None
    # V5: does the attached PDF belong to this reference?
    identity_status: str = "unverified"
    # V5.2: author-year letter, "(2018b)" -> "b" (citations must match it)
    year_suffix: str | None = None
    # V5.8 G3: the uploaded PDF was unusable and replaced (library / open access)
    replaced_upload_reason: str | None = None
    # Free-full-text hint from OpenAlex (models/open_access.py); metadata only
    oa_status: str | None = None
    oa_url: str | None = None
    oa_pdf_url: str | None = None
    oa_license: str | None = None
    oa_version: str | None = None


class ClaimDB(SQLModel, table=True):
    """Database model for extracted claims."""

    __tablename__ = "claims"

    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="sessions.id", index=True)
    claim_number: int
    manuscript_text: str = ""
    paragraph_text: str = ""
    extracted_claim: str = ""
    claim_type: str = "factual"
    reference_ids_json: str = "[]"
    priority: str = "medium"
    section_heading: str = ""
    atomic_claims_json: str = "[]"
    location_json: str | None = None
    skipped: bool = False
    # V5: references cited together in the same sentence
    co_cited_count: int = 1
    # V5.2: clause this reference is cited for ("" = whole sentence / legacy row),
    # "fragment" for incomplete sentences, and an in-text citation that fits
    # several references (reference_ids holds the best guess).
    cited_for: str = ""
    claim_quality: str = "ok"
    mapping_ambiguous: bool = False
    candidate_reference_ids_json: str = "[]"


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
    # V2 fields
    model_reasoning_json: str | None = None
    cannot_verify_reason: str | None = None
    section_relevance: str = "high"
    text_quality_score: float = 1.0
    retry_strategy_used: str | None = None
    retry_attempts: int = 0
    # V4/V5 layer trace (votes kept for the UI voting panel)
    votes_json: str | None = None
    consensus_type: str = ""
    final_tier: int = 0
    escalation_path_json: str = "[]"
    total_models_consulted: int = 0
    agreement_ratio: float = 0.0
    # V5 cascade fields
    decided_by: str = "none"
    screen_p_support: float | None = None
    screen_p_contradict: float | None = None
    screen_p_topic: float | None = None
    layer_path_json: str = "[]"
    cost_usd: float = 0.0
    latency_ms: int = 0
    quotes_validated: bool | None = None
    # V5.4 partial sub-types (models/partial_types.py)
    partial_type: str | None = None
    partial_severity: str | None = None
    author_action: str = ""
    unsupported_elements_json: str = "[]"
    guards_applied_json: str = "[]"


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
