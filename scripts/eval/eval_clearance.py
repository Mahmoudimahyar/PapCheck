"""The screen auto-clear rule and label mapping, evaluated on stored item records.

Auto-clear in production (spec §0) = every code gate holds (full text, text
quality, no non-year digits, no negation cue, <= 60 words, not a contrast,
no refusal, contains_instructions below the cut-off, screen enabled) AND
s >= t_accept AND the L2 verifier co-signs ("supported" with >= 1 validated
"supports" quote). Records keep the gate failures other than the s
threshold, so the rule can be re-evaluated at any t_accept.
"""

from eval_models import GOLD_LABELS, ItemRecord, LayerRecord

THRESHOLD_GATE = "below_threshold"
# Policy gates that a calibration decides; dropped from records so clearance can be
# re-scored at any threshold even when the app's screen.json has auto-clear off.
POLICY_GATES = frozenset({THRESHOLD_GATE, "auto_clear_off"})
# cannot_verify reasons that mean "the source does not establish the claim".
INSUFFICIENT_REASONS = frozenset({"insufficient_in_source", "abstract_insufficient"})


def verifier_layer(rec: ItemRecord) -> LayerRecord | None:
    """The decisive L2 call: the expanded re-run when there was one, else the first."""
    verifiers = [lay for lay in rec.layers if lay.role == "verifier"]
    return verifiers[-1] if verifiers else None


def has_verifier(rec: ItemRecord) -> bool:
    return verifier_layer(rec) is not None


def verifier_cosigns(rec: ItemRecord) -> bool:
    layer = verifier_layer(rec)
    return layer is not None and layer.cosigns


def screen_passes(rec: ItemRecord, t_accept: float) -> bool:
    """Gates + s >= t_accept (no verifier involvement)."""
    screen = rec.screen
    if screen is None or not screen.ok or screen.s is None:
        return False
    return not rec.gate_failures and screen.s >= t_accept


def cleared(rec: ItemRecord, t_accept: float, cosign: bool) -> bool:
    """Whole clearance rule at t_accept (with or without the verifier co-sign)."""
    if not screen_passes(rec, t_accept):
        return False
    return verifier_cosigns(rec) if cosign else True


def predicted_label(rec: ItemRecord) -> str | None:
    """Our verdict on the 5 gold labels; None = error / not a verdict (screen mode).

    Mapping (data.md caveat 3): insufficient_evidence and cannot_verify for
    "not in source" reasons count as not_supported (the source does not
    establish the claim); llm_error and other failures are errors.
    """
    verdict = rec.verdict
    if verdict in GOLD_LABELS:
        return verdict
    if verdict == "insufficient_evidence":
        return "not_supported"
    if verdict == "cannot_verify" and rec.cannot_verify_reason in INSUFFICIENT_REASONS:
        return "not_supported"
    return None


def auto_cleared(rec: ItemRecord, t_accept: float | None) -> bool | None:
    """Whether the pair was (or would be) auto-cleared by the screen in this mode.

    cascade / recorded app run: decided_by == "screen"; screen: gates + s >= t;
    verifier with a screen: gates + s >= t + co-sign; judge/confirm: None.
    """
    if rec.mode in ("cascade", "recorded"):
        return rec.decided_by == "screen"
    if t_accept is None or rec.screen is None:
        return None
    if rec.mode == "screen":
        return cleared(rec, t_accept, cosign=False)
    if rec.mode == "verifier":
        return cleared(rec, t_accept, cosign=True)
    return None
