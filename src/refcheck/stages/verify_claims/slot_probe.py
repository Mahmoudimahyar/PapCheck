"""Blind slot probe (V5.7 #15, experimental): one cheap question for a flagged "supported".

Off by default: REFCHECK_SLOT_PROBE=on enables it (it also needs REFCHECK_ADJUDICATE;
REFCHECK_V57_DISABLE=15 turns it off). check_first.py runs it only when the shown
verdict is "supported", the check-first triage flagged it (check_first_reasons) and the
cited span has a relation, effect direction or population word (slot_probe_rules.
find_slots, <= 3).

One call (slot_probe_call.py: role "adjudicator", prompts/slot_probe.md) sees the pack
the shown verdict was based on and the cited span with those words masked, and says what
the source states in each slot. A slot whose answer differs, with an exact quote, becomes
an element ("relation: '... justifies ...'"). The elements go to ONE element-adjudicator
call (adjudicate.run_adjudication: the usual exact-quote clearing). Survivors make the
pair partially_supported, typed by kind (slot_probe_rules.KIND_TYPE; a "contradicted"
survivor -> specific_detail_mismatch, major; else minor), with a note per survivor, a
review flag and consensus "adjudicated" (a disputed / unconfirmed one is kept).
Otherwise the verdict stays. Once the probe ran, one trace layer "slot_probe" (both
calls' cost) is recorded; a failed element check adds a note and a review flag.
"""

import os
from typing import TYPE_CHECKING

from refcheck.llm import CostTracker
from refcheck.models.partial_types import GENUINE_PRECEDENCE
from refcheck.stages.verify_claims.adjudicate import (
    Adjudication,
    adjudicate_enabled,
    run_adjudication,
)
from refcheck.stages.verify_claims.layers import LayerResult, pack_for
from refcheck.stages.verify_claims.outcome_rules import demoted, rule_layer
from refcheck.stages.verify_claims.slot_probe_call import PROBE_LAYER, Finding, run_probe
from refcheck.stages.verify_claims.slot_probe_rules import KIND_TYPE, Slot, element_for
from refcheck.stages.verify_claims.v57 import enabled
from refcheck.stages.verify_claims.verifier_helpers import PairContext

if TYPE_CHECKING:
    from refcheck.stages.verify_claims.cascade import CascadeOutcome

__all__ = ["PROBE_LAYER", "PROBE_NOTE_OPENING", "probe_outcome", "slot_probe_enabled"]

PROBE_NOTE_OPENING = "Slot probe:"
_ON = frozenset({"1", "true", "yes", "on"})


def slot_probe_enabled() -> bool:
    """REFCHECK_SLOT_PROBE=on (default off), the element adjudicator on and #15 not in
    REFCHECK_V57_DISABLE."""
    value = os.getenv("REFCHECK_SLOT_PROBE", "off").strip().lower()
    return value in _ON and enabled(15) and adjudicate_enabled()


def _evidence_layer(out: "CascadeOutcome") -> LayerResult | None:
    """The layer whose pack the shown verdict was based on (a cross-check saw the
    verifier's), as adjudicate_apply.evidence_layer."""
    label = out.label_layer
    if label is None or label.output is None or label.role != "confirm":
        return label
    return next((lay for lay in reversed(out.layers) if lay.role == "verifier"
                 and lay.axis is not None), label)


def _merged(probe: LayerResult, adj: Adjudication | None, text: str,
            out: "CascadeOutcome") -> LayerResult:
    """The probe's trace layer (verdict unchanged), with both calls' cost."""
    label_out = out.label_layer.output if out.label_layer is not None else None
    other = adj.meta if adj is not None else LayerResult(layer="", role="adjudicator")
    output = label_out.model_copy(update={
        "explanation": text, "quotes": [], "unsupported_elements": [], "benign_notes": [],
        "dismissed": []}) if label_out is not None and probe.error is None else None
    return probe.model_copy(update={
        "output": output, "cost_usd": probe.cost_usd + other.cost_usd,
        "latency_ms": probe.latency_ms + other.latency_ms,
        "input_tokens": probe.input_tokens + other.input_tokens,
        "output_tokens": probe.output_tokens + other.output_tokens})


def _record(out: "CascadeOutcome", layer: LayerResult, notes: list[str] | None = None,
            ) -> "CascadeOutcome":
    update: dict[str, object] = {"layers": [*out.layers, layer],
                                 "layer_path": [*out.layer_path, PROBE_LAYER]}
    if notes:
        update |= {"notes": [*out.notes, *notes], "needs_review": True}
    return out.model_copy(update=update)


def _note(f: Finding, tail: str) -> str:
    return (f"{PROBE_NOTE_OPENING} asked without the claim's words, the source gives "
            f"'{f.answer}' for '{f.slot.text}' [{f.quote.passage_id}]; {tail}.")


def _demote(out: "CascadeOutcome", layer: LayerResult, survivors: list[Finding],
            contradicted: bool) -> "CascadeOutcome":
    types = sorted({KIND_TYPE[f.slot.kind] for f in survivors}, key=GENUINE_PRECEDENCE.index)
    ptype = "specific_detail_mismatch" if contradicted else types[0]
    kinds = ", ".join(sorted({f.slot.kind for f in survivors}))
    partial = rule_layer(out, [element_for(f.slot) for f in survivors],
                         "major" if contradicted else "minor",
                         f"Slot probe: the source does not state the claim's {kinds}.",
                         partial_type=ptype, name=PROBE_LAYER)
    if partial is None:  # no label output: cannot happen for a routed "supported"
        return _record(out, layer)
    meta = {k: getattr(layer, k) for k in ("model_id", "model_display", "provider",
                                           "latency_ms", "cost_usd", "input_tokens",
                                           "output_tokens", "pack_summary")}
    partial = partial.model_copy(update=meta)
    notes, consensus = demoted(out, "adjudicated")
    return out.model_copy(update={
        "verdict": "partially_supported", "label_layer": partial,
        "layers": [*out.layers, partial], "layer_path": [*out.layer_path, PROBE_LAYER],
        "notes": [*notes, *(_note(f, "the element check did not clear it") for f in survivors)],
        "consensus_type": consensus, "needs_review": True})


async def probe_outcome(ctx: PairContext, out: "CascadeOutcome", slots: list[Slot], part: str,
                        tracker: CostTracker | None, deadline: float) -> "CascadeOutcome":
    """The outcome after the probe of ``slots`` of the cited ``part`` (module doc)."""
    source = _evidence_layer(out)
    if out.verdict != "supported" or source is None or not slots \
            or PROBE_LAYER in out.layer_path:
        return out
    pack = pack_for(ctx, source.pack_kind)
    probe = await run_probe(ctx, pack, source.pack_kind, part, slots, tracker, deadline)
    if probe.meta.error is not None or not probe.findings:
        text = f"Slot probe: no slot differs from the source. {probe.explanation}".strip()
        return _record(out, _merged(probe.meta, None, text, out))
    adj = await run_adjudication(ctx, pack, source.pack_kind,
                                 [element_for(f.slot) for f in probe.findings], tracker, deadline)
    layer = _merged(probe.meta, adj, f"Slot probe: {probe.explanation} Element check: "
                    f"{adj.explanation or adj.meta.error or ''}".strip(), out)
    if not adj.ok:
        return _record(out, layer, [_note(f, "the element check failed, please check")
                                    for f in probe.findings])
    kept = [(f, d) for f, d in zip(probe.findings, adj.decisions, strict=True) if not d.cleared]
    if not kept:
        return _record(out, layer)
    return _demote(out, layer, [f for f, _ in kept], any(d.category == "contradicted"
                                                          for _, d in kept))
