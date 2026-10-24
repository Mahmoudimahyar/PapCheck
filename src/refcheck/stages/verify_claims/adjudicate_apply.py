"""When the element adjudicator runs and how its decisions change a routed outcome.

Runs once per pair, after routing, when the shown verdict is partially_supported
(any path) and lists at least one element. It checks the shown layer's elements
plus the verifier's and the cross-check's whenever that layer is partial too or
the pair is disputed, so a partial both models confirmed has both objections
checked (deduplicated, <= 6). Never on negative / undecided verdicts. Its call
sees the evidence pack the shown verdict was based on (a cross-check saw the
routed verifier's pack).

* every element cleared -> supported, guards from the categories
  (adjudicate_result.py) on top of the pipeline's (evidence_recheck), EXCEPT when
  the pair is disputed or its cross-check failed (dispute.py: the adjudicator never
  turns a dispute into plain "supported"), or no validated source quote supports it:
  then "held" - the partial is kept with every element, a note per cleared
  element and a review flag;
* some cleared -> partially_supported with only the survivors (also for a
  dispute; type: adjudicate_result.survivor_type);
* none cleared, or the call failed / was refused / over budget -> unchanged.

V5.7 (each off with REFCHECK_V57_DISABLE): #6 a figure credit's visual-only or
dropped-hedge survivors become notes (credit_rubric.py); #13 elements cleared ONLY by
co-cited references with framing / broadened survivors -> not_supported,
tangential_source (adjudicate_tangential.py); #11 an "unchanged" outcome is typed
from the survivors too (adjudicate_result.retyped); #2 a supported outcome's claim slots are audited
(slot_apply.py) before the deterministic rules.

Then, when the pair is still partial, the co-cited full-text union check may run
once (cocited_union.py / cocited_union_apply.py: "adjudicate_cocited" in layer_path).
Last, on EVERY routed outcome, the deterministic rules (outcome_rules.py, V5.6: a
figure the source states differently, an impossible lineage connective, a figure
credit verified on provenance only). Elements those rules add are never asked about.

The layer is always recorded ("adjudicate" in layer_path + one trace entry);
decided_by is kept and consensus_type becomes "adjudicated" when the result
changed (a "disputed" / "verifier_unconfirmed" consensus is kept for the review UI).
"""

from typing import TYPE_CHECKING

from rapidfuzz.utils import default_process

from refcheck.llm import CostTracker
from refcheck.stages.verify_claims.adjudicate import (
    LAYER,
    Adjudication,
    adjudicate_enabled,
    run_adjudication,
)
from refcheck.stages.verify_claims.adjudicate_result import (
    KEEP_CONSENSUS,
    adjudicated_layer,
    element_note,
    hold_reason,
    retyped,
)
from refcheck.stages.verify_claims.adjudicate_rules import is_locked
from refcheck.stages.verify_claims.adjudicate_summary import (
    AdjudicationSummary,
    Outcome,
    summarize,
)
from refcheck.stages.verify_claims.adjudicate_tangential import (
    cocited_only,
    tangential_layer,
    tangential_note,
)
from refcheck.stages.verify_claims.cocited_union_apply import union_outcome
from refcheck.stages.verify_claims.credit_rubric import credit_rubric, panel_cleared
from refcheck.stages.verify_claims.layers import LayerResult, pack_for
from refcheck.stages.verify_claims.outcome_rules import apply_outcome_rules
from refcheck.stages.verify_claims.partial_fields import type_layer
from refcheck.stages.verify_claims.recheck import is_listed
from refcheck.stages.verify_claims.slot_apply import slot_outcome
from refcheck.stages.verify_claims.verifier_helpers import PairContext

if TYPE_CHECKING:
    from refcheck.stages.verify_claims.cascade import CascadeOutcome

__all__ = ["AdjudicationSummary", "Outcome", "adjudicate_outcome", "apply_adjudication",
           "evidence_layer", "outcome_elements", "summarize"]
MAX_ELEMENTS = 6


def _last(layers: list[LayerResult], role: str) -> LayerResult | None:
    found = [lay for lay in layers if lay.role == role and lay.axis is not None]
    return found[-1] if found else None


def evidence_layer(out: "CascadeOutcome") -> LayerResult | None:
    """The layer whose pack the shown verdict was based on."""
    label = out.label_layer
    if label is not None and label.role != "confirm":
        return label
    return _last(out.layers, "verifier") or label


def outcome_elements(out: "CascadeOutcome") -> list[str]:
    """Elements to check (module doc): the shown layer's first, <= 6."""
    others = [_last(out.layers, "verifier"), _last(out.layers, "confirm")]
    sources = [type_layer(out.verdict, out.label_layer, out.layers),
               *(lay for lay in others if lay is not None and (
                   out.consensus_type == "disputed" or lay.verdict == "partially_supported"))]
    found: list[str] = []
    for lay in sources:
        for element in lay.output.unsupported_elements if lay and lay.output else []:
            # punctuation-blind: "two-stage scheme" and "two stage scheme" are one element
            if not is_listed(default_process(element), [default_process(f) for f in found]):
                found.append(element)
    return found[:MAX_ELEMENTS]


def _held(out: "CascadeOutcome", adj: Adjudication, reason: str) -> "CascadeOutcome":
    notes = [element_note(d) for d in adj.cleared]
    notes.append("Element check: every element the first check called unsupported was judged "
                 f"benign, but the verdict stays partially supported because {reason}; "
                 "please check.")
    return out.model_copy(update={"notes": [*out.notes, *notes], "needs_review": True})


def _tangential(out: "CascadeOutcome", adj: Adjudication, label: LayerResult,
                path: list[str]) -> "CascadeOutcome":
    """V5.7 #13 (adjudicate_tangential.py): not_supported, tangential_source."""
    layer = tangential_layer(adj, label)
    keep = out.consensus_type in KEEP_CONSENSUS
    return out.model_copy(update={
        "layer_path": path, "adjudication": summarize(adj, tangential=True),
        "layers": [*out.layers, layer], "verdict": "not_supported", "label_layer": layer,
        "notes": [*out.notes, tangential_note(adj)], "needs_review": True,
        "consensus_type": out.consensus_type if keep else "adjudicated"})


def apply_adjudication(out: "CascadeOutcome", adj: Adjudication,
                       ctx: PairContext | None = None) -> "CascadeOutcome":
    """The outcome after the adjudicator's decisions (module doc)."""
    label, base = out.label_layer, type_layer(out.verdict, out.label_layer, out.layers)
    label_out = label.output if label is not None else None
    base_out = base.output if base is not None else None
    path = [*out.layer_path, LAYER]
    if not adj.ok or label is None or label_out is None or base is None or base_out is None:
        return out.model_copy(update={"layer_path": path, "adjudication": summarize(adj),
                                      "layers": [*out.layers, adj.meta]})
    adj = credit_rubric(ctx, adj) if ctx is not None else adj
    if cocited_only(adj):
        return _tangential(out, adj, label, path)
    abstract_only = ctx is not None and ctx.coverage != "full_text"  # V5.7 #11
    reason = hold_reason(out, adj, label)
    trace: dict[str, object] = {"layer_path": path,
                                "adjudication": summarize(adj, held=reason is not None)}
    if not adj.cleared or reason is not None:  # recorded for the trace; the verdict stays
        layer = adjudicated_layer(adj, label, label_out, base_out, out.verdict, adj.decisions,
                                  abstract_only)
        kept = out.model_copy(update={**trace, "layers": [*out.layers, layer]})
        if reason is not None:
            return _held(kept, adj, reason)
        typed = retyped(label, base_out, adj.surviving, abstract_only)  # V5.7 #11
        return kept if typed is None else kept.model_copy(update={"label_layer": typed})
    verdict = "partially_supported" if adj.surviving else "supported"
    layer = adjudicated_layer(adj, label, label_out, base_out, verdict, adj.surviving,
                              abstract_only)
    notes = [element_note(d) for d in adj.cleared]
    if verdict == "supported":
        notes.insert(0, "Element check: every element the first check called unsupported was "
                     "cleared, so the verdict is supported instead of partially supported.")
    return out.model_copy(update={
        **trace, "layers": [*out.layers, layer], "verdict": verdict, "label_layer": layer,
        "notes": [*out.notes, *notes],
        "needs_review": out.needs_review or out.consensus_type in KEEP_CONSENSUS
        or panel_cleared(adj),
        "consensus_type": out.consensus_type if out.consensus_type in KEEP_CONSENSUS
        else "adjudicated"})


async def adjudicate_outcome(ctx: PairContext, out: "CascadeOutcome",
                             tracker: CostTracker | None, deadline: float) -> "CascadeOutcome":
    """Adjudicate a partial outcome when it applies, audit a supported one's claim slots
    (slot_apply.py, V5.7 #2), then the deterministic rules."""
    out = await _adjudicate(ctx, out, tracker, deadline)
    out = await slot_outcome(ctx, out, evidence_layer(out), tracker, deadline)
    return apply_outcome_rules(ctx, out)


async def _adjudicate(ctx: PairContext, out: "CascadeOutcome",
                      tracker: CostTracker | None, deadline: float) -> "CascadeOutcome":
    if not adjudicate_enabled() or out.verdict != "partially_supported" \
            or LAYER in out.layer_path:
        return out
    elements, source = outcome_elements(out), evidence_layer(out)
    if all(is_locked(e) for e in elements) or source is None:  # also: no elements
        return out
    pack = pack_for(ctx, source.pack_kind)
    adj = await run_adjudication(ctx, pack, source.pack_kind, elements, tracker, deadline)
    applied = apply_adjudication(out, adj, ctx)
    return await union_outcome(ctx, applied, adj, tracker, deadline)
