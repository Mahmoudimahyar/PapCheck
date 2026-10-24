"""The slot audit's adjudicator call and its effect on a "supported" outcome (V5.7 #2).

Runs after the element adjudicator / co-cited union check and before the deterministic
rules (adjudicate_apply.adjudicate_outcome) when the shown verdict is supported, the
source is full text and slot_audit.slot_phrases found phrases (it needs
REFCHECK_ADJUDICATE; off with REFCHECK_V57_DISABLE=2). A slot a co-cited reference states
is left to the adjudicator's "cocited" category (it sees the co-cited abstracts), not
exempted by a whole-text lexical match in a co-cited paper. NOT held-out: that choice was
informed by a gold TEST-split pair (the exemption hid one of its misses); the trigger
fires on no DEV pair, so dev cannot decide it, and #2's test numbers are not held-out. One
element-adjudicator call (same prompt and clearing rule: an exact quote; framing / wording
never clear a slot phrase the quote does not state) sees the pack the verdict was based on:

* every slot phrase cleared -> unchanged (the layer stays in the trace);
* a phrase survives -> partially_supported, minor, typed by its class (time frame ->
  specific_detail_mismatch, mechanism / recommendation -> unsupported_inference,
  population -> scope_overgeneralized; the most severe wins), the survivors as its
  elements, one note each and a review flag; the "now supported" notes of the
  element checks are dropped and the consensus becomes "adjudicated" (a disputed /
  unconfirmed one is kept);
* the call failed / over budget -> unchanged.

V5.8 #31 (F10): a cited-span phrase a supporting quote negates ("are used" vs "not
widely used", slot_polarity.py) is asked about the same way ("polarity: '...'").

Layer SLOT_LAYER ("adjudicate_slots", role adjudicator).
"""

from typing import TYPE_CHECKING

from refcheck.llm import CostTracker
from refcheck.models.partial_types import GENUINE_PRECEDENCE, LEGACY_FOR_TYPE
from refcheck.models.verification import JudgeOutput
from refcheck.stages.verify_claims import v57
from refcheck.stages.verify_claims.adjudicate import (
    Adjudication,
    adjudicate_enabled,
    run_adjudication,
)
from refcheck.stages.verify_claims.adjudicate_result import KEEP_CONSENSUS, adjudicated_layer
from refcheck.stages.verify_claims.layers import LayerResult, cited_for, pack_for
from refcheck.stages.verify_claims.post_checks import searchable_text
from refcheck.stages.verify_claims.slot_audit import SlotPhrase, polarity_slots, slot_phrases
from refcheck.stages.verify_claims.verifier_helpers import PairContext

if TYPE_CHECKING:
    from refcheck.stages.verify_claims.cascade import CascadeOutcome

SLOT_LAYER = "adjudicate_slots"
_SUPPORTED_NOTE = "instead of partially supported"  # the element checks' "now supported" notes


def slot_note(slot: SlotPhrase) -> str:
    if slot.against:  # V5.8 #31
        return (f"Slot check: the cited text asserts '{slot.phrase}' but a supporting quote "
                f"says '{slot.against}' (opposite polarity); please check.")
    return (f"Slot check: the cited text adds a {slot.slot} ('{slot.phrase}') that the source "
            "states nowhere in its full text; please check.")


def _slot_type(survivors: list[SlotPhrase]) -> str:
    types = [s.partial_type for s in survivors]
    return min(types, key=GENUINE_PRECEDENCE.index)


def slot_layer(adj: Adjudication, label: LayerResult, survivors: list[SlotPhrase]) -> LayerResult:
    """The partial the surviving slot phrases make of ``label`` (module doc)."""
    base = label.output
    ptype = _slot_type(survivors)
    explanation = "Slot check: " + "; ".join(slot_note(s) for s in survivors)
    output = JudgeOutput.model_validate({
        "verdict": "partially_supported", "confidence": base.confidence if base else 0.5,
        "quotes": [{"passage_id": q.passage_id, "text": q.text, "role": q.role}
                   for q in label.validated_quotes],
        "severity": "minor", "problem_type": LEGACY_FOR_TYPE.get(ptype, "not_in_source"),
        "explanation": f"{explanation} First check: {base.explanation if base else ''}".strip(),
        "missing": None, "partial_type": ptype,
        "unsupported_elements": [s.element for s in survivors]})
    return adj.meta.model_copy(update={"layer": SLOT_LAYER, "output": output,
                                       "validated_quotes": list(label.validated_quotes)})


def _demote(out: "CascadeOutcome", layer: LayerResult, survivors: list[SlotPhrase],
            path: list[str]) -> "CascadeOutcome":
    notes = [n for n in out.notes if not (n.startswith("Element check:")
                                          and _SUPPORTED_NOTE in n)]
    keep = out.consensus_type in KEEP_CONSENSUS
    return out.model_copy(update={
        "verdict": "partially_supported", "label_layer": layer, "layer_path": path,
        "layers": [*out.layers, layer], "notes": [*notes, *map(slot_note, survivors)],
        "needs_review": True, "consensus_type": out.consensus_type if keep else "adjudicated"})


def _applies(ctx: PairContext, out: "CascadeOutcome") -> bool:
    return v57.enabled(2) and adjudicate_enabled() and out.verdict == "supported" \
        and ctx.coverage == "full_text" and out.label_layer is not None \
        and SLOT_LAYER not in out.layer_path


async def slot_outcome(ctx: PairContext, out: "CascadeOutcome", source: LayerResult | None,
                       tracker: CostTracker | None, deadline: float) -> "CascadeOutcome":
    """The outcome after the slot audit (module doc); ``source``: the layer whose pack
    the shown verdict was based on (adjudicate_apply.evidence_layer)."""
    if not _applies(ctx, out) or source is None or out.label_layer is None:
        return out
    label = out.label_layer
    quotes = [q.text for q in label.validated_quotes]
    cited = cited_for(ctx.claim, ctx.claim_text) or ctx.claim_text
    slots = slot_phrases(cited, searchable_text(ctx.doc), quotes)
    slots += polarity_slots(cited, [q.text for q in label.quotes("supports")])
    if not slots:
        return out
    by_element = {s.element: s for s in slots}
    adj = await run_adjudication(ctx, pack_for(ctx, source.pack_kind), source.pack_kind,
                                 list(by_element), tracker, deadline)
    path = [*out.layer_path, SLOT_LAYER]
    survivors = [by_element[d.element] for d in adj.surviving if d.element in by_element]
    if not adj.ok or not survivors:
        meta = adj.meta if not adj.ok or label.output is None else adjudicated_layer(
            adj, label, label.output, label.output, "supported", [])
        meta = meta.model_copy(update={"layer": SLOT_LAYER})
        return out.model_copy(update={"layer_path": path, "layers": [*out.layers, meta]})
    return _demote(out, slot_layer(adj, label, survivors), survivors, path)
