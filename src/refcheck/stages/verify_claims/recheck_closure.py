"""After the evidence re-check (recheck.py): close the first run's elements (V5.7 #1, #11).

#1 closure. A re-run that upgrades a verdict to "supported" replaced the first verdict
wholesale, so the elements the first run raised were never closed. On the V4.9 gold
replay the partial -> supported flips were right 12 times out of 13; the wrong one is
the only flip whose first run had NO validated "supports" quote, and the overturned
negative (04473-type) ended "supported" on the cross-check alone. So an upgrade to
"supported" is final only when the first run was partially_supported WITH a validated
supports quote. Otherwise a routed "supported" becomes partially_supported with the
first run's elements (``closure_layer``: the re-check layer's quotes, on the re-check
pack) and goes to the existing element adjudicator, which clears an element only with
an exact quote (adjudicate_rules.py): every element cleared -> supported (unless the
adjudicator's hold rules apply), any survivor -> partial.

#11 (re-check part). A partial re-run that reports the same elements as the first run
keeps the first run's partial_type / severity / problem_type (``keep_first_type``): a
type flip on identical findings is sampling noise, not new evidence. When the
survivors changed, the re-run's type stands. The recorded layer trace keeps what the
model said.

Both are switched off with REFCHECK_V57_DISABLE (v57.py).
"""

from typing import TYPE_CHECKING

from refcheck.models.partial_types import is_genuine
from refcheck.stages.verify_claims import v57
from refcheck.stages.verify_claims.layers import LayerResult
from refcheck.stages.verify_claims.recheck import is_listed, upgraded

if TYPE_CHECKING:
    from refcheck.stages.verify_claims.cascade import CascadeOutcome

PARTIAL = "partially_supported"


def _elements(lay: LayerResult) -> list[str]:
    return list(lay.output.unsupported_elements) if lay.output is not None else []


def closure_needed(first: LayerResult, second: LayerResult) -> bool:
    """The re-run upgraded ``first`` to "supported" and that upgrade is not final (doc)."""
    if second is first or second.verdict != "supported" or not upgraded(first, second):
        return False
    if not _elements(first):
        return False
    return not (first.verdict == PARTIAL and bool(first.quotes("supports")))


def closure_layer(first: LayerResult, second: LayerResult) -> LayerResult:
    """The re-check layer as a partial with the first run's elements and classification."""
    assert first.output is not None and second.output is not None
    out = second.output.model_copy(update={
        "verdict": PARTIAL, "unsupported_elements": _elements(first),
        "partial_type": first.output.partial_type, "severity": first.output.severity,
        "problem_type": first.output.problem_type, "explanation": first.output.explanation,
        "missing": first.output.missing, "benign_notes": [], "dismissed": []})
    return second.model_copy(update={"output": out})


def closure_note(first: LayerResult) -> str:
    """Why a re-checked "supported" was sent back to the element check."""
    why = ("gave no supporting quote that could be validated" if first.verdict == PARTIAL
           else f"said {first.verdict}")
    shown = "; ".join(f"'{e}'" for e in _elements(first))
    return (f"Evidence re-check: the re-run found support, but the first check {why}, so "
            f"its elements ({shown}) were checked one by one against the re-check passages; "
            "the verdict stays partially supported unless each is shown to be stated.")


def close_recheck(out: "CascadeOutcome", first: LayerResult | None,
                  second: LayerResult | None) -> "CascadeOutcome":
    """The routed outcome, or the closure partial when #1 applies (module doc)."""
    if (first is None or second is None or out.verdict != "supported"
            or not v57.enabled(1) or not closure_needed(first, second)):
        return out
    return out.model_copy(update={
        "verdict": PARTIAL, "label_layer": closure_layer(first, second),
        "recheck_cleared": [], "notes": [*out.notes, closure_note(first)]})


def same_elements(a: list[str], b: list[str]) -> bool:
    """Both lists report the same elements (rewordings allowed, recheck.is_listed)."""
    return all(is_listed(e, b) for e in a) and all(is_listed(e, a) for e in b)


def keep_first_type(first: LayerResult, second: LayerResult) -> LayerResult:
    """``second`` with the first run's classification when #11 applies (module doc)."""
    one, two = first.output, second.output
    if (one is None or two is None or second is first or not v57.enabled(11)
            or first.verdict != PARTIAL or second.verdict != PARTIAL
            or not is_genuine(one.partial_type) or one.partial_type == two.partial_type
            or not same_elements(_elements(first), _elements(second))):
        return second
    kept = two.model_copy(update={"partial_type": one.partial_type, "severity": one.severity,
                                  "problem_type": one.problem_type})
    return second.model_copy(update={"output": kept})
