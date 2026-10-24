"""Summary metrics for an eval run.

Headline numbers exclude synthetic items (data.md caveat 3); they are
reported separately, together with a per-dataset breakdown. Errors (failed
calls, budget exhaustion, timeouts) are excluded from the classification
metrics and counted in `n_errors`. Each block carries the scoring-hygiene metrics and the
summary the per-group blocks (dev/test, flagged rows, subset roles; eval_hygiene).
"""

from collections import Counter, defaultdict
from collections.abc import Sequence

from eval_clearance import auto_cleared, predicted_label
from eval_hygiene import Hygiene, compute_hygiene, group_records
from eval_models import GOLD_LABELS, ItemRecord, RunMeta
from eval_partial import PartialMetrics, compute_partial
from eval_recorded import OfflineReport
from eval_stats import (
    BinaryMetrics,
    accuracy,
    binary_metrics,
    clopper_pearson_upper,
    macro_f1,
    per_class_f1,
    percentile,
    safe_div,
)
from pydantic import BaseModel, Field


class AutoClear(BaseModel):
    """Screen auto-clear: coverage and the gold-problem rate among cleared pairs."""

    n_cleared: int
    coverage: float | None
    problems: int
    problem_rate: float | None
    cp_upper_95: float


class MetricBlock(BaseModel):
    """Metrics over one set of records (headline, a dataset, or synthetic)."""

    n: int
    n_scored: int
    n_errors: int
    accuracy_6way: float | None = None
    macro_f1: float | None = None
    per_class_f1: dict[str, float] = Field(default_factory=dict)
    problem: BinaryMetrics = Field(default_factory=BinaryMetrics)
    auto_clear: AutoClear | None = None
    layer_rates: dict[str, float] = Field(default_factory=dict)  # share of pairs per layer
    # V5.1: the judge only sees unusual positives; negatives get the blind cross-check.
    escalation_rate: float | None = None  # share of pairs that reached the judge (L3)
    cross_check_rate: float | None = None  # share of pairs that got the confirm call
    decided_by: dict[str, int] = Field(default_factory=dict)
    consensus: dict[str, int] = Field(default_factory=dict)  # confirmed / disputed / ...
    adjudication: dict[str, int] = Field(default_factory=dict)  # cleared / partial / ...
    cocited_union: dict[str, int] = Field(default_factory=dict)  # co-cited union check
    review_rate: float | None = None
    flagged_by_fine_label: dict[str, str] = Field(default_factory=dict)  # "k/n" flagged
    confusion: dict[str, dict[str, int]] = Field(default_factory=dict)  # gold -> pred
    partial: PartialMetrics | None = None  # 3-way / harshness / partial sub-types
    hygiene: Hygiene | None = None  # TPR/TNR, near/far misses, review tier (eval_hygiene)
    cost_usd: float = 0.0
    cost_per_1k_pairs: float | None = None
    latency_p50_ms: float | None = None
    latency_p90_ms: float | None = None
    cached_layer_calls: int = 0


class RunSummary(BaseModel):
    """summary.json: provenance + headline + breakdowns."""

    meta: RunMeta
    headline: MetricBlock
    by_dataset: dict[str, MetricBlock] = Field(default_factory=dict)
    synthetic: MetricBlock | None = None
    groups: dict[str, MetricBlock] = Field(default_factory=dict)  # eval_hygiene.group_records
    offline: OfflineReport | None = None  # --offline: calls a live run would still need


def _predicted_problem(rec: ItemRecord, t_accept: float | None) -> bool | None:
    if rec.mode == "screen":
        if rec.screen is None or not rec.screen.ok:
            return None  # screen call failed: an error, not a prediction
        cleared = auto_cleared(rec, t_accept)
        return None if cleared is None else not cleared
    label = predicted_label(rec)
    return None if label is None else label != "supported"


def _auto_clear(records: Sequence[ItemRecord], t_accept: float | None) -> AutoClear | None:
    flags = [auto_cleared(r, t_accept) for r in records]
    if not records or any(f is None for f in flags):
        return None
    cleared = [r for r, f in zip(records, flags, strict=True) if f]
    problems = sum(1 for r in cleared if r.gold_binary == "problem")
    return AutoClear(
        n_cleared=len(cleared), coverage=safe_div(len(cleared), len(records)),
        problems=problems, problem_rate=safe_div(problems, len(cleared)),
        cp_upper_95=clopper_pearson_upper(problems, len(cleared), 0.95),
    )


def _layer_rates(records: Sequence[ItemRecord]) -> dict[str, float]:
    counts: Counter[str] = Counter()
    for rec in records:
        counts.update({lay.layer for lay in rec.layers})
        if rec.screen is not None:
            counts["screen"] += 1
    return {name: round(count / len(records), 4) for name, count in sorted(counts.items())}


def _path_rate(records: Sequence[ItemRecord], layer: str) -> float | None:
    return safe_div(sum(1 for r in records if layer in r.layer_path), len(records))


def _confusion(records: Sequence[ItemRecord]) -> dict[str, dict[str, int]]:
    table: dict[str, Counter[str]] = defaultdict(Counter)
    for rec in records:
        pred = rec.verdict if rec.verdict != "cannot_verify" \
            else f"cannot_verify:{rec.cannot_verify_reason}"
        table[rec.gold_label][pred] += 1
    return {gold: dict(sorted(row.items())) for gold, row in sorted(table.items())}


def _flagged_by_fine(records: Sequence[ItemRecord],
                     flags: Sequence[bool | None]) -> dict[str, str]:
    groups: dict[str, list[bool]] = defaultdict(list)
    for rec, flag in zip(records, flags, strict=True):
        if flag is not None and rec.fine_label:
            groups[rec.fine_label].append(flag)
    return {name: f"{sum(vals)}/{len(vals)}" for name, vals in sorted(groups.items())}


def compute_block(records: Sequence[ItemRecord], t_accept: float | None) -> MetricBlock:
    """All metrics for a set of records (t_accept: the run's screen threshold)."""
    scored = [(r, label) for r in records if (label := predicted_label(r)) is not None]
    gold = [r.gold_label for r, _ in scored]
    pred = [label for _, label in scored]
    flags = [_predicted_problem(r, t_accept) for r in records]
    pairs = [(r.gold_binary == "problem", f) for r, f in zip(records, flags, strict=True)
             if f is not None]
    latencies = [float(r.latency_ms) for r in records if r.error is None]
    cost = sum(r.cost_usd for r in records)
    in_cascade = any(r.mode in ("cascade", "recorded") for r in records)
    screen_mode = any(r.mode == "screen" for r in records)
    labels = sorted(set(gold) | set(pred), key=lambda x: GOLD_LABELS.index(x))
    n_scored = len(pairs) if screen_mode else len(scored)
    return MetricBlock(
        n=len(records), n_scored=n_scored, n_errors=len(records) - n_scored,
        accuracy_6way=accuracy(gold, pred) if gold else None,
        macro_f1=macro_f1(gold, pred, labels) if gold else None,
        per_class_f1={k: round(v, 4) for k, v in per_class_f1(gold, pred, labels).items()},
        problem=binary_metrics([g for g, _ in pairs], [bool(f) for _, f in pairs]),
        auto_clear=_auto_clear(records, t_accept),
        layer_rates=_layer_rates(records) if records else {},
        escalation_rate=_path_rate(records, "judge") if in_cascade else None,
        cross_check_rate=_path_rate(records, "confirm") if in_cascade else None,
        decided_by=dict(Counter(r.decided_by for r in records)) if in_cascade else {},
        consensus=dict(Counter(r.consensus_type for r in records if r.consensus_type))
        if in_cascade else {},
        adjudication=dict(Counter(r.adjudication for r in records if r.adjudication)),
        cocited_union=dict(Counter(r.cocited_union for r in records if r.cocited_union)),
        review_rate=safe_div(sum(1 for r in records if r.needs_review), len(records)),
        flagged_by_fine_label=_flagged_by_fine(records, flags),
        confusion=_confusion(records), partial=compute_partial(records),
        hygiene=compute_hygiene(records),
        cost_usd=round(cost, 6),
        cost_per_1k_pairs=round(1000 * cost / len(records), 4) if records else None,
        latency_p50_ms=percentile(latencies, 50), latency_p90_ms=percentile(latencies, 90),
        cached_layer_calls=sum(1 for r in records for lay in r.layers if lay.cached),
    )


def summarize(records: Sequence[ItemRecord], meta: RunMeta) -> RunSummary:
    """Headline (non-synthetic), per-dataset (non-synthetic) and synthetic blocks."""
    t_accept = meta.thresholds.get("t_accept")
    t = float(t_accept) if isinstance(t_accept, float | int) \
        and not isinstance(t_accept, bool) else None
    real = [r for r in records if not r.synthetic]
    synthetic = [r for r in records if r.synthetic]
    datasets = sorted({r.dataset for r in real})
    return RunSummary(
        meta=meta, headline=compute_block(real, t),
        by_dataset={d: compute_block([r for r in real if r.dataset == d], t) for d in datasets},
        synthetic=compute_block(synthetic, t) if synthetic else None,
        groups={k: compute_block(v, t) for k, v in group_records(real).items()},
    )
