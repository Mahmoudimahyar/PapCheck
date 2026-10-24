"""A claim figure the source states differently (V5.6, review finding L3).

The manual review of 191 "supported" verdicts found a pair whose note said "Numbers
not found in the source: <figure>" while the verdict stayed supported: the source's
own figure for the same quantity was about 15 times larger. This check turns such a
"supported" verdict into partially_supported (outcome_rules.py; the one post-routing
check besides the lineage check that may change a verdict; full-text sources only).

A conflict needs ALL of:

* a figure of the cited span occurs nowhere in the source (whole text + abstract,
  after numeric_text normalisation: glued units / words, comparison symbols, names,
  thousands written with a space);
* the source states figures of the SAME KIND (``same_kind``): the same unit, the same
  statistic label or every word after the claim figure also follows the source figure
  ("3,000 bone grafts" vs "48211 bone grafts", not "512 bone donors"), and, when both
  name an object after "in / of", a shared object word ("a 50% reduction in graft
  rejection" is not "a 20% reduction in IL-6 levels"). Stricter than
  source_numbers.figures_only_absent, because this changes a verdict. A source figure
  of 0 or with a leading zero ("000" of a split "10 000") is never compared;
* no figure of the same unit (and, for plain counts, a shared word) is within rounding
  of the claim figure (ratio < ROUNDING), whatever its words: "48 percent overall"
  may be what the claim's "50% reduction" rounds;
* every same-kind figure differs from the claim figure by MORE than FACTOR, after
  multiplier words ("9.5 million" is the same figure as "9,500,000"): a total twice
  the per-group figure is not flagged.

A claim stated as a bound ("more than X", "fewer than X") that ANY same-kind source
figure satisfies is a true bound: flagged only as a gross understatement (every
satisfying figure more than BOUND_FACTOR away), minor, naming the first satisfying
figure (never an unrelated one such as a control arm). Otherwise the conflict is
major and names the first same-kind figure in the text.
"""

from typing import Literal

from pydantic import BaseModel

from refcheck.stages.verify_claims.figure_kind import scaled
from refcheck.stages.verify_claims.source_numbers import (
    SourceQuantity,
    found_in,
    quantities,
    source_index,
)

FACTOR = 2.0
BOUND_FACTOR = 5.0
ROUNDING = 1.25


class FigureConflict(BaseModel):
    """A claim figure and the same-kind figure the source states instead."""

    claim: str  # as shown to the author ("3,000")
    source: str  # ("48,211")
    severity: Literal["minor", "major"]
    bound: bool = False  # the claim is a true lower / upper bound of the source's figures

    @property
    def element(self) -> str:
        return f"number: source says {self.source}; manuscript says {self.claim}"

    @property
    def note(self) -> str:
        why = (" The claim is a true bound of the source's figure, so the mismatch is minor."
               if self.bound else "")
        return (f"Number check: the source says {self.source} where the manuscript says "
                f"{self.claim}, and states the figure nowhere; the verdict is partially "
                f"supported instead of supported.{why}")


def shown(q: SourceQuantity) -> str:
    """The figure for a note: whole numbers >= 1,000 with thousands separators."""
    if q.decimals == 0 and not q.unit and q.value >= 1000:
        return f"{int(q.value):,}"
    return q.text


def _comparable(q: SourceQuantity) -> bool:
    """Not 0 and not a leading-zero fragment ("000", "05")."""
    return q.value != 0 and not (q.text.startswith("0") and "." not in q.text.split()[0])


def _objects_meet(a: SourceQuantity, b: SourceQuantity) -> bool:
    return not (a.object_words and b.object_words) or bool(
        set(a.object_words) & set(b.object_words))


def same_kind(claim_q: SourceQuantity, source_q: SourceQuantity) -> bool:
    """Same unit, the same statistic label or the claim's words, and a shared object
    word when both name one (module doc)."""
    if claim_q.unit != source_q.unit or not _objects_meet(claim_q, source_q):
        return False
    if claim_q.label and claim_q.label == source_q.label:
        return True
    words = set(scaled(claim_q.value, claim_q.nouns)[1])
    return bool(words) and words <= set(scaled(source_q.value, source_q.nouns)[1])


def _loosely_same(claim_q: SourceQuantity, source_q: SourceQuantity) -> bool:
    """Same unit; for plain counts also a shared word (counts are everywhere in a paper)."""
    if claim_q.unit != source_q.unit:
        return False
    return bool(claim_q.unit) or bool(set(claim_q.nouns + claim_q.object_words)
                                      & set(source_q.nouns + source_q.object_words))


def _ratio(a: float, b: float) -> float:
    low, high = sorted((abs(a), abs(b)))
    return high / low if low > 0 else float("inf")


def _value(q: SourceQuantity) -> float:
    return scaled(q.value, q.nouns)[0]


def _satisfies(q: SourceQuantity, v: float) -> bool:
    value = _value(q)
    return (q.bound == "lower" and v > value) or (q.bound == "upper" and v < value)


def _conflict(q: SourceQuantity, same: list[SourceQuantity]) -> FigureConflict | None:
    value = _value(q)
    within = [s for s in same if _satisfies(q, _value(s))]
    if within:  # a true bound: only a gross understatement counts, minor
        if min(_ratio(value, _value(s)) for s in within) <= BOUND_FACTOR:
            return None
        return FigureConflict(claim=shown(q), source=shown(within[0]), severity="minor",
                              bound=True)
    if min(_ratio(value, _value(s)) for s in same) <= FACTOR:
        return None
    return FigureConflict(claim=shown(q), source=shown(same[0]), severity="major")


def _rounded(q: SourceQuantity, pool: tuple[SourceQuantity, ...]) -> bool:
    value = _value(q)
    return any(_comparable(s) and _loosely_same(q, s) and _ratio(value, _value(s)) < ROUNDING
               for s in pool)


def figure_conflict(claim_part: str, source_text: str) -> FigureConflict | None:
    """The first claim figure the source states differently (module doc), else None."""
    if not claim_part.strip() or not source_text.strip():
        return None
    pool = source_index(source_text)
    for q in quantities(claim_part):
        if q.value == 0 or found_in(q, pool) or _rounded(q, pool):
            continue
        same = [s for s in pool if _comparable(s) and same_kind(q, s)]
        if same and (conflict := _conflict(q, same)) is not None:
            return conflict
    return None
