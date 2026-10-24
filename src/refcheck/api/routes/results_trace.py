"""Derive the V5 layer trace summary shown in the UI from a stored result.

``model_reasoning`` holds one entry per layer in ``layer_path`` order
(screen first when it ran). Confirmation status follows the V5.1 cascade:
a negative verifier verdict gets a blind cross-check (confirm layer); the
cascade's consensus_type says "disputed" (cross-check disagreed) or
"verifier_unconfirmed" (cross-check / judge call failed), both flagged for
review. Otherwise the deciding layers (verifier + confirm, or verifier +
judge) agreeing on the positive/negative axis = "confirmed" when they come
from different model families, "same_family" otherwise. Results stored
before V5.1 ran confirm only to break a verifier/judge tie = "disputed".
"""

from typing import Literal

from refcheck.llm.model_registry import get_spec
from refcheck.models.verification import ModelReasoning, VerificationResult
from refcheck.stages.generate_report.layer_trace import (
    SCREEN_VERDICTS,
    VERIFIER_LAYERS,
    layer_names,
)

__all__ = [
    "CONFIRMATION_LABELS", "SCREEN_VERDICTS", "ConfirmationStatus", "axis_of",
    "confirmation_status", "layer_names", "model_family", "screen_p_problem",
]

ConfirmationStatus = Literal["confirmed", "disputed", "unconfirmed", "same_family", "none"]
Axis = Literal["positive", "negative"]

POSITIVE = frozenset({"supported", "partially_supported"})
NEGATIVE = frozenset({"not_supported", "contradicted", "not_relevant"})

CONFIRMATION_LABELS: dict[ConfirmationStatus, str] = {
    "confirmed": "Confirmed by 2 model families",
    "disputed": "Disputed — needs review",
    "unconfirmed": "Unconfirmed — needs review",
    "same_family": "Agreed by 2 models of the same family",
    "none": "",
}
_CONSENSUS_STATUS: dict[str, ConfirmationStatus] = {
    "disputed": "disputed", "verifier_unconfirmed": "unconfirmed",
}

_NAME_PREFIXES: tuple[tuple[str, str], ...] = (
    ("claude", "anthropic"), ("gpt", "openai"), ("o1", "openai"), ("o3", "openai"),
    ("o4", "openai"), ("text-embedding", "openai"), ("gemini", "gemini"), ("grok", "xai"),
)


def axis_of(verdict: str) -> Axis | None:
    """Positive/negative axis of a verdict (None = no side taken)."""
    if verdict in POSITIVE:
        return "positive"
    if verdict in NEGATIVE:
        return "negative"
    return None


def model_family(model_name: str) -> str:
    """Model family (= provider) for the independent-confirmation check."""
    spec = get_spec(model_name)
    if spec is not None:
        return spec.family
    name = model_name.strip().lower()
    if "/" in name:
        return name.split("/", 1)[0]
    for prefix, family in _NAME_PREFIXES:
        if name.startswith(prefix):
            return family
    return name


def _last(entries: list[tuple[str, ModelReasoning]], *layers: str) -> ModelReasoning | None:
    found = [entry for name, entry in entries if name in layers]
    return found[-1] if found else None


def confirmation_status(v: VerificationResult) -> ConfirmationStatus:
    """How independently the final verdict was confirmed."""
    if v.verdict == "cannot_verify" or v.user_override:
        return "none"
    if v.consensus_type in _CONSENSUS_STATUS:
        return _CONSENSUS_STATUS[v.consensus_type]
    entries = list(zip(layer_names(v), v.model_reasoning, strict=True))
    if {"confirm", "judge"} <= {name for name, _ in entries}:
        return "disputed"  # pre-V5.1: confirm only ran to break a verifier/judge tie
    verifier = _last(entries, *VERIFIER_LAYERS)
    second = _last(entries, "confirm", "judge")  # V5.1 never runs both
    if verifier is None or second is None:
        return "none"
    axis = axis_of(second.verdict)
    if axis is None or axis != axis_of(verifier.verdict):
        return "none"
    if model_family(verifier.model_name) == model_family(second.model_name):
        return "same_family"
    return "confirmed"


def screen_p_problem(v: VerificationResult) -> float | None:
    """P(problem) = 1 - s from the fast screen (risk ranking); None if no screen."""
    if v.screen_p_support is None:
        return None
    return round(1.0 - v.screen_p_support, 4)
