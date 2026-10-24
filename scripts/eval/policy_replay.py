"""Offline replay of the cascade's dispute policy on recorded runs (no API calls).

A "dispute" is a NEGATIVE verifier verdict that the blind cross-family check
(role "confirm") does not share. A policy maps (verifier verdict, cross-check
verdict) to the verdict shown to the user; every other pair keeps its recorded
verdict. Policies are scored on:

* recorded cascade runs (items.jsonl with verifier + confirm layers);
* paired runs: a verifier-mode run of the verifier model and one of the
  confirm model on the same items (the confirm role re-runs the verifier's
  template on the same pack, so its verdict stands in for the cross-check);
* the manual gold of a real manuscript (verifier/cross-check verdicts per case).
"""

from collections.abc import Callable, Sequence

from eval_clearance import predicted_label, verifier_layer
from eval_models import ItemRecord, LayerRecord
from eval_stats import BinaryMetrics, accuracy, binary_metrics
from pydantic import BaseModel

from refcheck.stages.verify_claims.dispute import disputed_verdict

Policy = Callable[[str, str | None], str]
POSITIVE = frozenset({"supported", "partially_supported"})
NEGATIVE = frozenset({"not_supported", "contradicted", "not_relevant"})
CAP = "partially_supported"
# Manual labels that accept more than one verdict / none of the cascade's verdicts.
GOLD_ACCEPTS: dict[str, frozenset[str]] = {
    "partially_supported_tool_ok": frozenset({"partially_supported", "not_supported"}),
    "wrong_paper": frozenset(),  # needs the identity/mapping fixes, not a verdict rule
}


def keep_verifier(verifier: str, confirm: str | None) -> str:
    """Pre-V5.2 rule: a dispute keeps the verifier's (harsher) verdict."""
    return verifier


def softer_capped(verifier: str, confirm: str | None) -> str:
    """Any negative + positive cross-check -> partially_supported (the less severe view,
    capped: never plain "supported" from a dispute)."""
    return CAP if confirm in POSITIVE else verifier


def not_supported_only(verifier: str, confirm: str | None) -> str:
    """Only not_supported + positive cross-check -> partially_supported."""
    return CAP if confirm in POSITIVE and verifier == "not_supported" else verifier


def step_down_all(verifier: str, confirm: str | None) -> str:
    """One step toward the cross-check, contradicted included (-> not_supported)."""
    steps = {"not_supported": CAP, "not_relevant": "not_supported",
             "contradicted": "not_supported"}
    return steps.get(verifier, verifier) if confirm in POSITIVE else verifier


def confirm_wins(verifier: str, confirm: str | None) -> str:
    """Show the cross-check's verdict whenever it is decisive."""
    return confirm if confirm in POSITIVE or confirm in NEGATIVE else verifier


POLICIES: dict[str, Policy] = {
    "keep_verifier (old)": keep_verifier,
    "softer_capped (all negatives -> partial)": softer_capped,
    "not_supported_only (-> partial)": not_supported_only,
    "step_down_all (NS->partial, NR/contradicted->NS)": step_down_all,
    "confirm_wins": confirm_wins,
    "production dispute.py (NS->partial, NR->NS, contradicted kept)": disputed_verdict,
}


class Scores(BaseModel):
    """6-way accuracy and binary problem detection over scored items."""

    n: int
    accuracy_6way: float | None
    problem: BinaryMetrics


def as_label(verdict: str) -> str | None:
    """Shown verdict -> gold label space (insufficient = the source does not establish it)."""
    if verdict in POSITIVE or verdict in NEGATIVE:
        return verdict
    return "not_supported" if verdict == "insufficient_evidence" else None


def _confirm_layer(rec: ItemRecord) -> LayerRecord | None:
    confirms = [lay for lay in rec.layers if lay.role == "confirm" and lay.verdict]
    return confirms[-1] if confirms else None


def replay_cascade(rec: ItemRecord, policy: Policy) -> str | None:
    """Predicted gold label of a cascade record under ``policy``."""
    verifier, confirm = verifier_layer(rec), _confirm_layer(rec)
    if verifier is None or confirm is None or verifier.verdict not in NEGATIVE:
        return predicted_label(rec)
    if confirm.verdict in NEGATIVE:  # agreement: unchanged by any dispute rule
        return predicted_label(rec)
    return as_label(policy(verifier.verdict or "", confirm.verdict))


def replay_paired(verifier_rec: ItemRecord, confirm_rec: ItemRecord | None,
                  policy: Policy) -> str | None:
    """Verifier-mode record + the confirm model's record on the same item."""
    own = predicted_label(verifier_rec)
    if verifier_rec.verdict not in NEGATIVE or confirm_rec is None:
        return own
    other = confirm_rec.verdict
    if other in NEGATIVE:
        return own
    return as_label(policy(verifier_rec.verdict, other))


def score(gold: Sequence[str], pred: Sequence[str | None]) -> Scores:
    """Scores over the items with a prediction (gold "supported" = no problem)."""
    pairs = [(g, p) for g, p in zip(gold, pred, strict=True) if p is not None]
    return Scores(
        n=len(pairs), accuracy_6way=accuracy([g for g, _ in pairs], [p for _, p in pairs])
        if pairs else None,
        problem=binary_metrics([g != "supported" for g, _ in pairs],
                               [p != "supported" for _, p in pairs]))


def gold_agrees(manual: str, shown: str) -> bool:
    """Whether a shown verdict matches a manual review label."""
    return shown in GOLD_ACCEPTS.get(manual, frozenset({manual}))
