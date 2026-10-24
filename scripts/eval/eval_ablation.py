"""Per-split metrics of a run and the delta table of the V5.7 proposal ablation
(ablate_v57.py): every variant against the all-on run, dev and test apart.

Columns: missed partial (gold partial shown supported), over-harsh (gold supported shown
partial or negative), 3-way accuracy, type accuracy (gold partials the tool flagged; an
evidence_gap counts as coverage_limited), review-tier recall (gold partials flagged by the
verdict or surfaced by needs_review / check first) and needs_call (pairs an --offline run
scored from its fallback run because a call missed the cache).
"""

from collections.abc import Mapping, Sequence

from eval_hygiene import compute_hygiene
from eval_models import ItemRecord
from eval_partial import compute_partial
from eval_report import table
from pydantic import BaseModel

SPLITS = ("dev", "test")


class SplitMetrics(BaseModel):
    n: int = 0
    missed_partial: str = "0/0"
    over_harsh: str = "0/0"
    acc3: float | None = None
    type_acc: float | None = None
    review_recall: float | None = None
    needs_call: int = 0


def split_metrics(records: Sequence[ItemRecord]) -> SplitMetrics:
    """The ablation columns over ``records`` (synthetic rows left out)."""
    real = [r for r in records if not r.synthetic]
    partial, hygiene = compute_partial(real), compute_hygiene(real)
    if partial is None or hygiene is None:
        return SplitMetrics(n=len(real))
    return SplitMetrics(
        n=partial.n_scored, missed_partial=partial.missed_partial,
        over_harsh=partial.over_harsh, acc3=partial.accuracy_3way,
        type_acc=partial.partial_type_accuracy_flagged,
        review_recall=hygiene.review_tier_recall_partial, needs_call=hygiene.needs_call)


def metrics_by_split(records: Sequence[ItemRecord]) -> dict[str, SplitMetrics]:
    """dev, test (when the records carry a split) and all."""
    out = {s: split_metrics([r for r in records if r.split == s]) for s in SPLITS
           if any(r.split == s for r in records)}
    out["all"] = split_metrics(records)
    return out


def _count(ratio: str) -> int:
    return int(ratio.split("/")[0])


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{100 * value:.1f}%"


def _delta_int(value: int, base: int) -> str:
    return f" ({value - base:+d})" if value != base else ""


def _delta_pct(value: float | None, base: float | None) -> str:
    if value is None or base is None or abs(value - base) < 1e-9:
        return ""
    return f" ({100 * (value - base):+.1f})"


def row(name: str, m: SplitMetrics, base: SplitMetrics | None) -> list[str]:
    """One table row; deltas against ``base`` (none for the base row itself)."""
    b = base or m
    return [name, str(m.n),
            m.missed_partial + _delta_int(_count(m.missed_partial), _count(b.missed_partial)),
            m.over_harsh + _delta_int(_count(m.over_harsh), _count(b.over_harsh)),
            _pct(m.acc3) + _delta_pct(m.acc3, b.acc3),
            _pct(m.type_acc) + _delta_pct(m.type_acc, b.type_acc),
            _pct(m.review_recall) + _delta_pct(m.review_recall, b.review_recall),
            str(m.needs_call) + _delta_int(m.needs_call, b.needs_call)]


HEADER = ["config", "n", "missed partial", "over-harsh", "3-way", "type acc",
          "review recall", "needs_call"]


def delta_table(results: Mapping[str, Mapping[str, SplitMetrics]], base: str) -> list[str]:
    """Text tables per split: the base config first, then every variant with deltas."""
    splits = [s for s in (*SPLITS, "all") if any(s in r for r in results.values())]
    lines: list[str] = []
    for split in splits:
        ref = results.get(base, {}).get(split)
        rows = [row(name, by_split[split], None if name == base else ref)
                for name, by_split in results.items() if split in by_split]
        lines += [f"split={split} (deltas vs {base})", *table(HEADER, rows), ""]
    return lines
