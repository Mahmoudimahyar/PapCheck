"""Pure statistics for the eval: Clopper-Pearson bound, percentiles, F1 scores.

No numpy/scipy dependency: the exact one-sided Clopper-Pearson upper bound is
found by bisection on the binomial CDF (computed in log space, so it is
stable for thousands of trials).
"""

import math
from collections.abc import Sequence

from pydantic import BaseModel

_BISECTION_STEPS = 80


def _log_pmf(i: int, n: int, p: float) -> float:
    return (math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)
            + i * math.log(p) + (n - i) * math.log1p(-p))


def binom_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k) for X ~ Binomial(n, p)."""
    if k < 0:
        return 0.0
    if k >= n or p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 0.0
    logs = [_log_pmf(i, n, p) for i in range(k + 1)]
    top = max(logs)
    return min(1.0, math.exp(top) * sum(math.exp(x - top) for x in logs))


def clopper_pearson_upper(k: int, n: int, confidence: float = 0.95) -> float:
    """Exact one-sided upper confidence bound for a binomial proportion k/n.

    The bound u solves P(X <= k | n, u) = 1 - confidence (equivalently the
    `confidence` quantile of Beta(k + 1, n - k)). n == 0 or k == n gives 1.0.
    """
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be in (0, 1)")
    if n <= 0 or k >= n:
        return 1.0
    if k < 0:
        raise ValueError("k must be >= 0")
    alpha = 1.0 - confidence
    lo, hi = k / n, 1.0
    for _ in range(_BISECTION_STEPS):
        mid = (lo + hi) / 2.0
        if binom_cdf(k, n, mid) > alpha:
            lo = mid
        else:
            hi = mid
    return hi


def percentile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolated percentile (numpy's default method); None when empty."""
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q / 100.0
    low = math.floor(pos)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def safe_div(num: float, den: float) -> float | None:
    return num / den if den else None


class BinaryMetrics(BaseModel):
    """Positive class = "problem" (gold_binary == problem / predicted not-supported)."""

    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0
    precision: float | None = None
    recall: float | None = None
    f1: float | None = None


def binary_metrics(gold: Sequence[bool], pred: Sequence[bool]) -> BinaryMetrics:
    """Confusion counts plus precision / recall / F1 for the positive class."""
    if len(gold) != len(pred):
        raise ValueError("gold and pred differ in length")
    pairs = list(zip(gold, pred, strict=True))
    tp = sum(1 for g, p in pairs if g and p)
    fp = sum(1 for g, p in pairs if not g and p)
    fn = sum(1 for g, p in pairs if g and not p)
    tn = len(pairs) - tp - fp - fn
    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    f1 = None
    if precision is not None and recall is not None:
        f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return BinaryMetrics(tp=tp, fp=fp, fn=fn, tn=tn, precision=precision, recall=recall, f1=f1)


def per_class_f1(gold: Sequence[str], pred: Sequence[str],
                 labels: Sequence[str] | None = None) -> dict[str, float]:
    """F1 per label (labels default to the union of gold and predicted, like sklearn)."""
    if len(gold) != len(pred):
        raise ValueError("gold and pred differ in length")
    names = list(labels) if labels is not None else sorted(set(gold) | set(pred))
    scores: dict[str, float] = {}
    for name in names:
        tp = sum(1 for g, p in zip(gold, pred, strict=True) if g == name and p == name)
        fp = sum(1 for g, p in zip(gold, pred, strict=True) if g != name and p == name)
        fn = sum(1 for g, p in zip(gold, pred, strict=True) if g == name and p != name)
        scores[name] = 0.0 if tp == 0 else 2 * tp / (2 * tp + fp + fn)
    return scores


def macro_f1(gold: Sequence[str], pred: Sequence[str],
             labels: Sequence[str] | None = None) -> float | None:
    """Unweighted mean of per-class F1 (None when there is nothing to score)."""
    scores = per_class_f1(gold, pred, labels)
    return sum(scores.values()) / len(scores) if scores else None


def accuracy(gold: Sequence[str], pred: Sequence[str]) -> float | None:
    return safe_div(sum(1 for g, p in zip(gold, pred, strict=True) if g == p), len(gold))
