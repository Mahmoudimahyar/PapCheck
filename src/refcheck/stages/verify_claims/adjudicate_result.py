"""The element adjudicator's trace layer and notes (adjudicate_apply.py decides when).

* guards from the cleared categories: stated / wording -> overliteral_wording (the
  passage was in the evidence and the first check read it too literally), cocited
  -> cocited_share, framing -> author_framing_or_example;
* the survivors' type (``survivor_type``): when every survivor is contradicted,
  broadened or overstated (any contradicted suffices), the type they imply
  (specific_detail_mismatch / scope_overgeneralized / certainty_overstated, the most
  severe wins). It replaces the routed layer's type only when it is MORE severe
  (GENUINE_PRECEDENCE) or the routed type is the default missing_element: a
  scope_overgeneralized partial whose last survivor the model calls "overstated"
  stays scope_overgeneralized (major) instead of becoming certainty_overstated (minor).
  V5.7 #11: ``retyped`` applies the same rule to an "unchanged" outcome; on an abstract,
  all-"absent" survivors replace unsupported_inference with missing_element (shown as
  coverage_limited, partial_fields). Rejected on gold DEV: the same on full text (-3 / +1
  types); typing disputes from survivors instead of the cross-check's type (-2 / +0).
  V5.8 (subtype_rules.py, part of #11): own share unsupported -> tangential_source
  (``adjudicated_layer``); survivors that are all exclusive terms ("X alone") ->
  certainty_overstated over any routed type but tangential_source; the cross-check's
  specific_detail_mismatch with only absent, figure-free survivors -> missing_element.
  V5.8 #26 (subtype_round2.py) then refines the type from the survivors' wording.
"""

from typing import TYPE_CHECKING

from refcheck.models.partial_types import (
    GENUINE_PRECEDENCE,
    LEGACY_FOR_TYPE,
    BenignNote,
    default_severity,
)
from refcheck.models.verification import JudgeOutput
from refcheck.stages.verify_claims import v57
from refcheck.stages.verify_claims.adjudicate import Adjudication
from refcheck.stages.verify_claims.adjudicate_rules import ElementDecision
from refcheck.stages.verify_claims.layers import LayerResult
from refcheck.stages.verify_claims.partial_fields import genuine_type
from refcheck.stages.verify_claims.subtype_round2 import refined_type
from refcheck.stages.verify_claims.subtype_rules import (
    CERTAINTY,
    TANGENTIAL,
    exclusive_only,
    own_share_unsupported,
    unwitnessed_specific,
)

if TYPE_CHECKING:
    from refcheck.stages.verify_claims.cascade import CascadeOutcome

GUARD_FOR_CATEGORY: dict[str, BenignNote] = {
    "stated": "overliteral_wording", "cocited": "cocited_share",
    "framing": "author_framing_or_example", "wording": "overliteral_wording",
}
CATEGORY_TEXT = {"stated": "stated in the source", "cocited": "stated by a co-cited reference",
                 "framing": "the author's framing or an example",
                 "wording": "a wording difference only",
                 "panel_visual": "a figure-panel detail",  # V5.7 #6 (credit_rubric.py)
                 "panel_hedge": "a figure-legend wording"}
SURVIVOR_TYPE = {"contradicted": "specific_detail_mismatch",
                 "broadened": "scope_overgeneralized", "overstated": "certainty_overstated"}
_DEFAULT = "missing_element"
# V5.7 #11: routed types an all-absent survivor list replaces on an abstract-only source.
ABSENT_REPLACES = frozenset({"unsupported_inference"})
# Consensus kept on a changed result: the review UI must still show the disagreement.
KEEP_CONSENSUS = frozenset({"disputed", "verifier_unconfirmed"})


def element_note(d: ElementDecision) -> str:
    where = f" [{d.passage_id}]" if d.category in ("stated", "cocited") and d.passage_id else ""
    note = f": {d.note.rstrip('.')}" if d.note else ""
    return f"Element check: '{d.element}' - {CATEGORY_TEXT.get(d.category, d.category)}" \
        f"{where}{note}."


def _rank(partial_type: str) -> int:
    """Position in GENUINE_PRECEDENCE (lower = more severe); other types rank last."""
    order = GENUINE_PRECEDENCE
    return order.index(partial_type) if partial_type in order else len(order)


def all_absent(surviving: list[ElementDecision]) -> bool:
    """V5.7 #11: every survivor is merely absent (nothing shown states it)."""
    return v57.enabled(11) and bool(surviving) and all(d.category == "absent"
                                                        for d in surviving)


def implied_type(surviving: list[ElementDecision]) -> str | None:
    """The type the survivors' categories imply (module doc), else None."""
    if all_absent(surviving):
        return _DEFAULT
    if exclusive_only(surviving):  # V5.8: "X alone" is certainty_overstated
        return CERTAINTY
    implied = [SURVIVOR_TYPE.get(d.category) for d in surviving]
    if "specific_detail_mismatch" in implied:
        return "specific_detail_mismatch"
    found = [t for t in implied if t is not None]
    # V5.7 #11: an "absent" survivor does not veto the others' type
    whole = len(found) == len([d for d in surviving if d.category != "absent"]) \
        if v57.enabled(11) else len(found) == len(implied)
    return min(found, key=_rank) if found and whole else None


def _replaces(new: str, kept: str, surviving: list[ElementDecision],
              abstract_only: bool, cross_check: bool) -> bool:
    if new == kept:
        return False
    if abstract_only and new == _DEFAULT and kept in ABSENT_REPLACES and all_absent(surviving):
        return True
    if new == CERTAINTY and kept != TANGENTIAL and exclusive_only(surviving):
        return True
    if new == _DEFAULT and unwitnessed_specific(kept, surviving, cross_check):
        return True
    return kept == _DEFAULT or _rank(new) < _rank(kept)


def _typed(ptype: str) -> tuple[str, str, str]:
    return ptype, default_severity(ptype) or "minor", LEGACY_FOR_TYPE.get(ptype, "not_in_source")


def survivor_type(base: JudgeOutput, surviving: list[ElementDecision],
                  abstract_only: bool = False, cross_check: bool = False,
                  ) -> tuple[str, str, str]:
    """(partial_type, severity, problem_type) for the surviving elements (module doc;
    ``abstract_only``: the source is an abstract, V5.7 #11; ``cross_check``: the
    routed type is the cross-check's, V5.8)."""
    kept = genuine_type(base, "partially_supported")
    new = implied_type(surviving)
    typed = _typed(new) if new is not None and _replaces(
        new, kept, surviving, abstract_only, cross_check) else (kept, base.severity,
                                                                 base.problem_type)
    refined = refined_type(typed[0], surviving, abstract_only)  # V5.8 #26 (subtype_round2)
    return typed if refined == typed[0] else _typed(refined)


def adjudicated_layer(adj: Adjudication, label: LayerResult, label_out: JudgeOutput,
                      base_out: JudgeOutput, verdict: str, kept: list[ElementDecision],
                      abstract_only: bool = False) -> LayerResult:
    """The adjudicate layer as a JudgeOutput: ``verdict`` with the ``kept`` elements
    (``abstract_only``: see survivor_type)."""
    stated = [d.validated for d in adj.cleared if d.validated is not None]
    shown = label.quotes("supports") if verdict == "supported" else label.validated_quotes
    quotes = [*shown, *(q for q in stated if q.text not in {s.text for s in shown})]
    supported = verdict == "supported"
    ptype, severity, problem = _typed(TANGENTIAL) \
        if not supported and own_share_unsupported(adj, label, abstract_only) \
        else survivor_type(base_out, kept, abstract_only, label.role == "confirm")
    output = JudgeOutput.model_validate({
        "verdict": verdict, "confidence": label_out.confidence,
        "quotes": [{"passage_id": q.passage_id, "text": q.text, "role": q.role} for q in quotes],
        "severity": "none" if supported else severity,
        "problem_type": "none" if supported else problem,
        "explanation": f"Element check: {adj.explanation}".strip() if supported
        else label_out.explanation, "missing": None,
        "partial_type": "none" if supported else ptype,
        "unsupported_elements": [d.element for d in kept],
        "benign_notes": sorted({g for d in adj.cleared
                                if (g := GUARD_FOR_CATEGORY.get(d.category)) is not None})
        if supported else []})
    return adj.meta.model_copy(update={"output": output, "validated_quotes": quotes})


def retyped(label: LayerResult, base_out: JudgeOutput, surviving: list[ElementDecision],
            abstract_only: bool) -> LayerResult | None:
    """V5.7 #11: ``label`` with the survivors' type when it differs (an "unchanged"
    outcome), else None; elements, quotes and explanation stay as they were."""
    if not v57.enabled(11) or label.output is None or not surviving:
        return None
    ptype, severity, problem = survivor_type(base_out, surviving, abstract_only,
                                             label.role == "confirm")
    if ptype == genuine_type(label.output, "partially_supported"):
        return None
    output = label.output.model_copy(update={"partial_type": ptype, "severity": severity,
                                             "problem_type": problem})
    return label.model_copy(update={"output": output})


def hold_reason(out: "CascadeOutcome", adj: Adjudication, label: LayerResult,
                kind: str = "adjudicator") -> str | None:
    """Why a fully cleared partial is not shown as supported (adjudicate_apply doc), else
    None; the co-cited union check (``kind`` "union", cocited_union_apply) applies the
    same rule, except that V5.7 #4 releases a disputed / unconfirmed union hold whose
    every element was cleared with an exact quote (``released``)."""
    if not adj.cleared or adj.surviving:
        return None
    if kind == "union" and released(out, adj):
        return None
    if out.consensus_type == "disputed":
        return "the two models disagreed on this citation"
    if out.consensus_type == "verifier_unconfirmed":
        return "the cross-check failed, so no second model confirmed this result"
    if not label.quotes("supports") and not any(d.validated for d in adj.cleared):
        return "no source quote supporting the claim could be validated"
    return None


def released(out: "CascadeOutcome", adj: Adjudication) -> bool:
    """V5.7 #4: a disputed / unconfirmed pair whose elements were ALL cleared, each with
    an exact quote (this source or a co-cited one); the dispute stays visible."""
    return v57.enabled(4) and out.consensus_type in KEEP_CONSENSUS and bool(adj.cleared) \
        and not adj.surviving and all(d.quote for d in adj.cleared)
