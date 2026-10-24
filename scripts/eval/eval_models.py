"""Pydantic models shared by the eval scripts (dataset rows, per-item records; the run
config and provenance live in eval_config and are re-exported here)."""

from typing import Literal

from eval_config import EVAL_DIR, RESULTS_DIR, EvalConfig, Mode, RunMeta, SourceMode
from gold_models import GoldRow
from pydantic import BaseModel, ConfigDict, Field

__all__ = ["EVAL_DIR", "GOLD_LABELS", "RESULTS_DIR", "EvalConfig", "EvalItem", "GoldLabel",
           "ItemRecord", "LayerRecord", "MissedCall", "Mode", "RunMeta", "ScreenRecord",
           "SourceMode"]

GoldLabel = Literal["supported", "partially_supported", "not_supported", "contradicted",
                    "not_relevant"]
GOLD_LABELS: tuple[str, ...] = ("supported", "partially_supported", "not_supported",
                                "contradicted", "not_relevant")


class EvalItem(BaseModel):
    """One labelled claim-source pair (see ~/.refcheck/eval/manifest.json)."""

    model_config = ConfigDict(extra="ignore")

    id: str
    claim: str
    context: str = ""
    claim_raw: str = ""
    source_id: str
    source_title: str = ""
    source_text: str
    source_type: str = "full_text"  # "abstract" (SciFact) | "full_text" (Citation-Integrity)
    source_abstract: str | None = None
    source_retrieved: str | None = None
    gold_label: GoldLabel
    gold_binary: Literal["ok", "problem"]
    fine_label: str = ""
    dataset: str
    split: str = ""
    synthetic: bool = False
    # Manuscript gold rows (refcheck_v49_gold): the source is the reference's real PDF.
    gold_row: GoldRow | None = None
    gold_partial_type: str = ""
    gold_secondary_types: list[str] = Field(default_factory=list)  # V5.8 F15 (type match)
    tool_misread_type: str = ""
    gold_confidence: str = ""
    gold_source: str = ""  # gold rows: which review labelled the pair
    # Scoring groups (eval_hygiene): rows reported apart from the clean headline (e.g.
    # "etiquette", "label_noise") and the row's role in a subset ("fn" / "fp" / "control").
    eval_flags: list[str] = Field(default_factory=list)
    subset_role: str = ""


class ScreenRecord(BaseModel):
    """What the Decisions-API screen answered for one pair."""

    probs: dict[str, float] = Field(default_factory=dict)
    refused: list[str] = Field(default_factory=list)
    s: float | None = None
    model: str = ""
    latency_ms: int = 0
    cost_usd: float = 0.0
    input_tokens: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.model)


class LayerRecord(BaseModel):
    """One chat layer call (L2 verifier / L3 judge / L4 confirm)."""

    layer: str
    role: str
    model_id: str = ""
    verdict: str | None = None  # None when the call failed
    severity: str | None = None
    problem_type: str | None = None
    partial_type: str | None = None  # partial sub-type, once the layers output one
    confidence: float | None = None
    quote_roles: list[str] = Field(default_factory=list)  # roles of VALIDATED quotes
    invalid_quotes: int = 0
    latency_ms: int = 0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None
    error_kind: str | None = None
    pack_kind: str = "standard"
    cached: bool = False  # answered from the LLM disk cache (cost/latency 0)

    @property
    def cosigns(self) -> bool:
        """Verifier co-sign for auto-clear: "supported" + >= 1 validated supports quote."""
        return self.verdict == "supported" and "supports" in self.quote_roles


class MissedCall(BaseModel):
    """One paid call an --offline run could not answer from the cache (not sent)."""

    kind: Literal["chat", "embedding", "screen"]
    role: str = ""
    model: str = ""
    est_input_tokens: int = 0
    est_cost_usd: float = 0.0
    # A --live-roles call that got no answer (--live-check, --max-cost cap, failed call,
    # or its pair had already missed another call): reported as "live-chat:<role>".
    live: bool = False


class ItemRecord(BaseModel):
    """Per-item eval output (one line of items.jsonl)."""

    id: str
    dataset: str
    synthetic: bool = False
    gold_label: str
    gold_binary: str
    fine_label: str = ""
    mode: Mode
    coverage: str = ""
    quality_reason: str = ""
    retrieval_version: str = ""
    pack_tokens: int = 0
    screen: ScreenRecord | None = None
    gate_failures: list[str] = Field(default_factory=list)  # code gates other than s >= t
    clear_eligible: bool | None = None  # at the run's t_accept (None: no screen)
    layers: list[LayerRecord] = Field(default_factory=list)
    verdict: str = "error"  # final raw verdict ("n/a" in screen mode)
    cannot_verify_reason: str | None = None
    decided_by: str = "none"
    consensus_type: str = ""
    layer_path: list[str] = Field(default_factory=list)
    needs_review: bool = False
    cost_usd: float = 0.0
    latency_ms: int = 0
    error: str | None = None
    # Gold sub-types (manuscript gold) and the deciding layer's own classification.
    gold_partial_type: str = ""
    gold_secondary_types: list[str] = Field(default_factory=list)  # V5.8 F15 (type match)
    tool_misread_type: str = ""
    gold_confidence: str = ""
    severity: str = ""
    problem_type: str = ""
    # Product partial fields (cascade: VerificationResult; single modes: the layer's own).
    partial_type: str = ""
    partial_severity: str = ""
    guards_applied: list[str] = Field(default_factory=list)
    unsupported_elements: list[str] = Field(default_factory=list)
    # Element adjudicator (cascade): cleared / partial / held / unchanged / error ("" = not run)
    adjudication: str = ""
    adjudicated_elements: dict[str, int] = Field(default_factory=dict)  # category -> count
    # Co-cited union check after it: cleared / partial / held / unchanged / error / skipped
    cocited_union: str = ""
    check_first: bool = False  # report's "check first" signal (result_signals.check_first)
    # Scoring groups (copied from the EvalItem; eval_hygiene).
    split: str = ""
    gold_source: str = ""
    eval_flags: list[str] = Field(default_factory=list)
    subset_role: str = ""
    # --offline: calls that missed the cache (never sent); the verdict then comes from the
    # --fallback-from run (needs_call) and is not this run's own.
    needs_call: bool = False
    missed_calls: list[MissedCall] = Field(default_factory=list)
