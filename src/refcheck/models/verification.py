"""Verification result data models (V5 screen -> verify -> judge cascade)."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from refcheck.models.evidence import EvidenceSection
from refcheck.models.partial_types import BenignNote, PartialSeverity, PartialType

Verdict = Literal[
    "supported",
    "partially_supported",
    "not_supported",
    "contradicted",
    "cannot_verify",
    "not_relevant",
]
LayerVerdict = Literal[
    "supported", "partially_supported", "not_supported", "contradicted", "not_relevant",
    "insufficient_evidence",
]
ProblemType = Literal[
    "none", "overgeneralized", "certainty_overstated", "wrong_direction", "wrong_population",
    "numeric_mismatch", "not_in_source", "unrelated_source", "compound_part_only",
]
DecidedBy = Literal["screen", "verifier", "judge", "none"]

_MAX_QUOTES = 3
_MAX_ELEMENTS = 5


class EvidenceQuote(BaseModel):
    """A verbatim quote an LLM layer cites from the evidence pack."""

    passage_id: str  # "A" or "P3" — ids shown in the pack
    text: str  # verbatim, <= 60 words
    role: Literal["supports", "contradicts", "closest"]
    # V5.6: the part of the cited span this quote states ("" = context only, not evidence).
    states: str = ""


class Dismissal(BaseModel):
    """A concern the model considered and cleared, with the passage that clears it (V5.6).

    Code validates ``quote`` (this source's passages; for cocited_share a co-cited
    abstract) before any guard is recorded: no clearance without a quote.
    """

    element: str
    guard: BenignNote
    passage_id: str
    quote: str


class JudgeOutput(BaseModel):
    """Structured output shared by the verifier (L2), judge (L3) and confirm (L4) layers.

    Sent as a strict JSON schema; strict mode drops numeric/length limits,
    so they are enforced leniently here (clamp/truncate, never reject).
    """

    verdict: LayerVerdict
    severity: Literal["none", "minor", "major"]
    problem_type: ProblemType
    confidence: float  # self-reported; stored, never used for routing
    quotes: list[EvidenceQuote]
    explanation: str  # never "reasoning"/"thinking": Claude may refuse "reasoning extraction"
    missing: str | None
    # Taxonomy v1.1 (models/partial_types.py). Defaults keep older cached outputs parseable.
    partial_type: PartialType = "none"
    unsupported_elements: list[str] = Field(default_factory=list)  # <=5 short phrases
    benign_notes: list[BenignNote] = Field(default_factory=list)  # concerns considered + dismissed
    dismissed: list[Dismissal] = Field(default_factory=list)  # V5.6: each clearance + its quote

    @field_validator("confidence", mode="after")
    @classmethod
    def _clamp_confidence(cls, value: float) -> float:
        return min(1.0, max(0.0, value))

    @field_validator("quotes", mode="after")
    @classmethod
    def _cap_quotes(cls, value: list[EvidenceQuote]) -> list[EvidenceQuote]:
        return [q for q in value if q.text.strip()][:_MAX_QUOTES]

    @field_validator("unsupported_elements", mode="after")
    @classmethod
    def _cap_elements(cls, value: list[str]) -> list[str]:
        return [e.strip()[:160] for e in value if e and e.strip()][:_MAX_ELEMENTS]


class VoteRecord(BaseModel):
    """Lightweight per-layer vote stored on each verification result."""

    model_name: str = ""
    abbreviation: str = ""
    tier: int = 0
    verdict: str = ""
    confidence: float = 0.0


class ModelReasoning(BaseModel):
    """Detailed output of one layer (screen / verifier / judge / confirm)."""

    model_name: str = ""
    model_display: str = ""
    verdict: str = "cannot_verify"
    confidence: float = 0.0
    reasoning: str = ""
    evidence_quotes: list[str] = Field(default_factory=list)
    source_section_preview: str = ""
    response_time_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


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
    tier: int = 1  # V5: 1 screen / 2 verifier / 3 judge
    source_coverage: Literal[
        "full_text", "abstract_only", "relevant_sections", "no_source"
    ] = "no_source"
    needs_user_review: bool = False
    atomic_results: list["AtomicVerification"] | None = None
    user_override: bool = False
    user_override_reason: str = ""
    original_verdict: Verdict | None = None
    original_confidence: float | None = None
    evidence_sections: list[EvidenceSection] = Field(default_factory=list)
    # Per-layer votes (V4 name kept for the UI voting panel)
    votes: list[VoteRecord] = Field(default_factory=list)
    consensus_type: str = ""  # screen_clear / verifier / confirmed / disputed / judge / ...
    final_tier: int = 0
    escalation_path: list[int] = Field(default_factory=list)
    total_models_consulted: int = 0
    agreement_ratio: float = 0.0
    # V2: Quality & transparency fields
    model_reasoning: list[ModelReasoning] = Field(default_factory=list)
    cannot_verify_reason: str | None = None
    section_relevance: str = "high"
    text_quality_score: float = 1.0
    # V2: Retry workflow fields (kept for stored results; unused by V5)
    retry_strategy_used: str | None = None
    retry_attempts: int = 0
    # V5: cascade trace
    decided_by: DecidedBy = "none"
    screen_p_support: float | None = None  # s = min(...) of the screen predicates
    screen_p_contradict: float | None = None  # P(finding_conflicts)
    screen_p_topic: float | None = None  # P(topic_match)
    layer_path: list[str] = Field(default_factory=list)
    cost_usd: float = 0.0
    latency_ms: int = 0
    quotes_validated: bool | None = None  # None = no quotes to validate
    # V5.4: partial sub-types (models/partial_types.py)
    partial_type: str | None = None  # genuine type for partial/negative verdicts, else None
    partial_severity: PartialSeverity | None = None
    author_action: str = ""  # one sentence telling the author what to fix
    unsupported_elements: list[str] = Field(default_factory=list)
    guards_applied: list[str] = Field(default_factory=list)  # concerns cleared (GuardName)


def reached_llm(result: VerificationResult) -> bool:
    """Whether a pair was meant to be judged by the LLM cascade (circuit-breaker base).

    Excludes no-source pairs and pairs short-circuited for a source reason
    (scanned PDF, wrong paper, ...) that never reached a model.
    """
    if result.source_coverage == "no_source":
        return False
    short_circuit = (result.verdict == "cannot_verify" and not result.layer_path
                     and result.cannot_verify_reason != "llm_error")
    return not short_circuit


class AtomicVerification(BaseModel):
    """Verification of a single atomic claim (V2)."""

    atom: str = ""
    verified: bool | None = None
    evidence: str | None = None
