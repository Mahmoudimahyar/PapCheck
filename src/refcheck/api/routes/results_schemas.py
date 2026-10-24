"""Response schemas for verification results endpoints."""

from pydantic import BaseModel, Field

from refcheck.api.routes.results_trace import ConfirmationStatus
from refcheck.stages.generate_report.result_signals import ResultSignals


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
    not_relevant: int = 0
    # V5: how pairs were decided ("screen" / "verifier" / "judge" / "none")
    decided_by: dict[str, int] = Field(default_factory=dict)
    needs_review: int = 0
    total_cost_usd: float = 0.0
    # V5.4: partially supported results per sub-type (every genuine type +
    # coverage_limited, 0 included; "unclassified" = legacy rows) and severity;
    # supported results whose concern a benign guard cleared, in all and per guard.
    partial_types: dict[str, int] = Field(default_factory=dict)
    partial_severity: dict[str, int] = Field(default_factory=dict)
    guarded: int = 0
    guards: dict[str, int] = Field(default_factory=dict)
    # V5.8: LLM roles that ran degraded in this run (one sentence each), then each fix
    # once; empty when every role ran on its normal model.
    degraded_notices: list[str] = Field(default_factory=list)


class ClaimDetail(BaseModel):
    """Claim info included in results response."""

    manuscript_text: str = ""
    extracted_claim: str = ""
    claim_type: str = ""
    priority: str = ""
    # V5.2: clause this reference is cited for ("" = the whole sentence)
    cited_for: str = ""
    claim_quality: str = "ok"  # "fragment" = the sentence looks incomplete
    mapping_ambiguous: bool = False
    candidate_reference_ids: list[int] = Field(default_factory=list)
    mapping_note: str = ""  # why the reference is a best guess
    citation_markers: list[str] = Field(default_factory=list)


class VoteSummary(BaseModel):
    """Lightweight vote info for result items."""

    model_name: str = ""
    abbreviation: str = ""
    tier: int = 0
    verdict: str = ""
    confidence: float = 0.0


class ModelReasoningItem(BaseModel):
    """Per-layer reasoning detail (one entry per cascade layer in V5)."""

    layer: str = ""  # screen / verifier / verifier_expanded / verifier_recheck / judge / confirm
    # / adjudicate (element check, V5.5)
    model_name: str = ""
    model_display: str = ""
    verdict: str = "cannot_verify"
    confidence: float = 0.0
    reasoning: str = ""
    evidence_quotes: list[str] = Field(default_factory=list)
    response_time_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    source_section_preview: str = ""


class PartialFields(BaseModel):
    """V5.4: partial sub-type, severity, what the author should do, the elements the
    source does not state, and the benign guards that cleared a concern."""

    partial_type: str | None = None
    partial_severity: str | None = None
    author_action: str = ""
    unsupported_elements: list[str] = Field(default_factory=list)
    guards_applied: list[str] = Field(default_factory=list)


class ResultItem(PartialFields):
    """Single result in the results response (V5.4 fields from PartialFields)."""

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
    # V2: Quality & transparency fields
    model_reasoning: list[ModelReasoningItem] = Field(default_factory=list)
    cannot_verify_reason: str | None = None
    section_relevance: str = "high"
    text_quality_score: float = 1.0
    # V5: cascade trace
    decided_by: str = "none"
    screen_p_support: float | None = None
    screen_p_problem: float | None = None  # 1 - screen_p_support (risk ranking)
    screen_p_contradict: float | None = None
    screen_p_topic: float | None = None
    layer_path: list[str] = Field(default_factory=list)
    escalation_path: list[int] = Field(default_factory=list)
    votes: list[VoteSummary] = Field(default_factory=list)
    cost_usd: float = 0.0
    latency_ms: int = 0
    quotes_validated: bool | None = None
    confirmation: ConfirmationStatus = "none"
    confirmation_label: str = ""
    # V5.2: dispute views, secondary citation, numbers not in source, unusable PDF
    signals: ResultSignals = Field(default_factory=ResultSignals)


class ResultsResponse(BaseModel):
    """Full paginated results response."""

    summary: ResultsSummary
    results: list[ResultItem]
    total: int
    page: int
    per_page: int
