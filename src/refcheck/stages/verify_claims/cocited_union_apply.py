"""How the co-cited union check changes a partial outcome (cocited_union.py decides when).

Same rules as the element adjudicator (adjudicate_apply.py):

* every surviving element cleared -> supported; guard cocited_share (its author
  note asks to place each citation next to the clause it supports) on top of the
  guards the adjudicator's cleared categories and the pipeline already earned,
  EXCEPT a disputed pair or one whose cross-check failed: "held" - it stays
  partial with every element, a note per cleared element and a review flag. V5.7 #4:
  every element cleared with an exact quote (this source or a co-cited one) releases
  that hold: supported, consensus still "disputed" / "verifier_unconfirmed", review
  flag, the cleared-element notes and RELEASE_NOTE (adjudicator holds stay);
* some cleared -> partially_supported with only the survivors (also for a dispute);
  author_action follows the new first element (partial_fields);
* none cleared -> unchanged; a failed / over-budget call -> unchanged.

V5.8: after the call, an element the union could not clear is cleared as author framing
(#23, framing_rules.py) or as the twin of an element the adjudicator cleared with a quote
(#24, round2_rules.twin_of; opt-in; no quote, so it never releases a dispute);
``with_rules``, only for "absent" (#24: also "cocited") elements.

The layer is always recorded once it was called ("adjudicate_cocited" in layer_path +
one trace entry: model, cost, resulting verdict); notes name the co-cited reference
of each cleared element. A co-cited quote is never shown as THIS reference's evidence.
"""

from typing import TYPE_CHECKING

from refcheck.llm import CostTracker
from refcheck.models.adjudication import UnionOutcome, UnionSummary
from refcheck.stages.verify_claims.adjudicate import Adjudication
from refcheck.stages.verify_claims.adjudicate_result import (
    KEEP_CONSENSUS,
    adjudicated_layer,
    hold_reason,
    released,
)
from refcheck.stages.verify_claims.adjudicate_rules import ElementDecision
from refcheck.stages.verify_claims.cocited_union import (
    UNION_LAYER,
    UnionRun,
    budget_skip,
    cocited_union_enabled,
    own_share_supported,
    run_union,
    union_targets,
)
from refcheck.stages.verify_claims.cocited_union_pack import union_documents, union_sources
from refcheck.stages.verify_claims.cocited_union_rules import UnionDecision
from refcheck.stages.verify_claims.framing_rules import FRAMING_NOTE, is_scaffold
from refcheck.stages.verify_claims.partial_fields import type_layer
from refcheck.stages.verify_claims.round2_rules import twin_of
from refcheck.stages.verify_claims.verifier_helpers import PairContext

if TYPE_CHECKING:
    from refcheck.stages.verify_claims.cascade import CascadeOutcome

_NOTE_QUOTE_CHARS = 240
RELEASE_NOTE = ("Element check: the two models disagreed on this citation, but every element "
                "is stated, with an exact quote, by this source or a reference cited in the "
                "same sentence; shown as supported, please check.")


def with_rules(run: UnionRun, adj: Adjudication, cited: str) -> UnionRun:
    """V5.8 #23 / #24 on the decisions the union check could not clear (module doc):
    only for an element the adjudicator found "absent" (#24 also "cocited"), never an
    overstated / broadened / contradicted one. A twin clearance carries no quote."""
    twins = [(d.element, d.quote) for d in adj.cleared]
    category = {d.element: d.category for d in adj.decisions}
    decisions = []
    for d in run.decisions:
        kind = category.get(d.element, "")
        if not d.cleared and is_scaffold(d.element, cited, kind):
            d = d.model_copy(update={"cleared": True, "rule": "framing", "note": FRAMING_NOTE})
        elif not d.cleared and (twin := twin_of(d.element, twins, kind)) is not None:
            d = d.model_copy(update={"cleared": True, "rule": "twin", "quote": None,
                                     "twin": twin,
                                     "note": f"rule: the same point as the cleared '{twin}'"})
        decisions.append(d)
    return run.model_copy(update={"decisions": decisions})


def _cleared(d: ElementDecision, u: UnionDecision, adj: Adjudication) -> ElementDecision:
    """An element the union check (or a V5.8 rule after it) cleared, as a decision."""
    if u.rule == "framing":
        return ElementDecision(element=d.element, category="framing", cleared=True, note=u.note)
    twin = next((c for c in adj.cleared if u.rule == "twin" and c.element == u.twin), None)
    if twin is not None:  # no quote / passage of its own: never released (module doc)
        return ElementDecision(element=d.element, category=twin.category, cleared=True,
                               note=u.note)
    return ElementDecision(element=d.element, category="cocited", cleared=True,
                           note=f"stated by co-cited reference [{u.number}]",
                           passage_id=u.passage_id, quote=u.quote)


def union_note(d: UnionDecision) -> str:
    if d.rule:
        return f"Element check: '{d.element}' - {d.note}."
    quote = " ".join((d.quote or "").split())
    if len(quote) > _NOTE_QUOTE_CHARS:
        quote = quote[:_NOTE_QUOTE_CHARS].rsplit(" ", 1)[0] + " …"
    return (f"Element check: '{d.element}' is stated by co-cited reference [{d.number}] "
            f"({d.passage_id}: \"{quote}\").")


def combined(adj: Adjudication, run: UnionRun) -> Adjudication:
    """The adjudicator's decisions with each union-cleared element as a cleared "cocited"."""
    found = {d.element: d for d in run.cleared}
    decisions = [_cleared(d, u, adj)
                 if not d.cleared and (u := found.get(d.element)) is not None else d
                 for d in adj.decisions]
    text = f"{adj.explanation} Co-cited check: {run.explanation}".strip()
    return Adjudication(meta=run.meta, decisions=decisions, explanation=text)


def summary(run: UnionRun, outcome: UnionOutcome, refs: list[int],
            surviving: list[ElementDecision]) -> UnionSummary:
    return UnionSummary(outcome=outcome, model_id=run.meta.model_id, error=run.meta.error,
                        cleared={d.element: d.number for d in run.cleared if d.number},
                        surviving=[d.element for d in surviving], refs=refs)


def _record(out: "CascadeOutcome", update: dict[str, object],
            union: UnionSummary) -> "CascadeOutcome":
    adjudication = out.adjudication.model_copy(update={"union": union}) \
        if out.adjudication is not None else None
    return out.model_copy(update={**update, "adjudication": adjudication,
                                  "layer_path": [*out.layer_path, UNION_LAYER]})


def apply_union(out: "CascadeOutcome", adj: Adjudication, run: UnionRun,
                refs: list[int]) -> "CascadeOutcome":
    """The outcome after the union check's decisions (module doc)."""
    label = out.label_layer
    base = type_layer(out.verdict, label, out.layers)
    if not run.ok or label is None or label.output is None or base is None \
            or base.output is None:
        return _record(out, {"layers": [*out.layers, run.meta]},
                       summary(run, "error", refs, adj.surviving))
    both = combined(adj, run)
    reason = hold_reason(out, both, label, kind="union")
    if not run.cleared or reason is not None:  # recorded for the trace; the verdict stays
        layer = adjudicated_layer(both, label, label.output, base.output, out.verdict,
                                  adj.surviving)
        kept = _record(out, {"layers": [*out.layers, layer]}, summary(
            run, "held" if reason else "unchanged", refs, adj.surviving))
        if reason is None:
            return kept
        notes = [*map(union_note, run.cleared), "Element check: every remaining element is "
                 "stated by a co-cited reference, but the verdict stays partially supported "
                 f"because {reason}; please check."]
        return kept.model_copy(update={"notes": [*out.notes, *notes], "needs_review": True})
    verdict = "partially_supported" if both.surviving else "supported"
    layer = adjudicated_layer(both, label, label.output, base.output, verdict, both.surviving)
    notes = [union_note(d) for d in run.cleared]
    if verdict == "supported":
        notes.insert(0, "Element check: the elements this reference does not state are "
                     "stated by the other reference(s) cited in the same sentence, so the "
                     "verdict is supported instead of partially supported.")
        if released(out, both):
            notes.append(RELEASE_NOTE)
    keep = out.consensus_type in KEEP_CONSENSUS
    return _record(out, {
        "layers": [*out.layers, layer], "verdict": verdict, "label_layer": layer,
        "notes": [*out.notes, *notes], "needs_review": out.needs_review or keep,
        "consensus_type": out.consensus_type if keep else "adjudicated",
    }, summary(run, "partial" if both.surviving else "cleared", refs, both.surviving))


async def union_outcome(ctx: PairContext, out: "CascadeOutcome", adj: Adjudication,
                        tracker: CostTracker | None, deadline: float) -> "CascadeOutcome":
    """Run the co-cited union check on a still-partial outcome when it applies."""
    if not cocited_union_enabled() or not adj.ok or out.verdict != "partially_supported" \
            or UNION_LAYER in out.layer_path or out.label_layer is None:
        return out
    targets = union_targets(adj)
    docs = union_documents(ctx) if targets else []
    if not docs:
        return out
    if not own_share_supported(out.label_layer, adj):  # tangential, not a shared citation
        union = UnionSummary(outcome="skipped", surviving=[d.element for d in targets])
        adjudication = out.adjudication.model_copy(update={"union": union}) \
            if out.adjudication is not None else None
        return out.model_copy(update={"adjudication": adjudication})
    early = budget_skip(out.label_layer.pack_kind, tracker, deadline)
    if early is not None:  # no retrieval (embeddings) once the budget or time is spent
        return apply_union(out, adj, early, [number for number, _, _ in docs])
    elements = [d.element for d in targets]
    sources = await union_sources(ctx, elements, tracker)
    if not sources:
        return out
    run = await run_union(ctx, sources, elements, out.label_layer.pack_kind, tracker, deadline)
    run = with_rules(run, adj, str(getattr(ctx.claim, "cited_for", "") or "") or ctx.claim_text)
    return apply_union(out, adj, run, [s.number for s in sources])
