"""Unit tests for scripts/eval/eval_stats.py (Clopper-Pearson, percentiles, F1)."""

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "eval"))

from eval_stats import (  # noqa: E402
    accuracy,
    binary_metrics,
    binom_cdf,
    clopper_pearson_upper,
    macro_f1,
    per_class_f1,
    percentile,
)


def test_binom_cdf_matches_direct_sum() -> None:
    n, p = 12, 0.3
    for k in range(n + 1):
        direct = sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k + 1))
        assert binom_cdf(k, n, p) == pytest.approx(direct, rel=1e-9)


def test_binom_cdf_edges() -> None:
    assert binom_cdf(-1, 10, 0.5) == 0.0
    assert binom_cdf(10, 10, 0.5) == 1.0
    assert binom_cdf(3, 10, 0.0) == 1.0
    assert binom_cdf(3, 10, 1.0) == 0.0


@pytest.mark.parametrize("n", [1, 10, 98, 99, 500])
def test_cp_upper_zero_failures_closed_form(n: int) -> None:
    # k = 0: P(X <= 0) = (1 - u)^n = alpha  ->  u = 1 - alpha^(1/n)
    assert clopper_pearson_upper(0, n, 0.95) == pytest.approx(1 - 0.05 ** (1 / n), abs=1e-9)


def test_cp_upper_rule_of_three_needs_about_100_clean_items_for_3_percent() -> None:
    assert clopper_pearson_upper(0, 98, 0.95) > 0.03
    assert clopper_pearson_upper(0, 99, 0.95) <= 0.03


@pytest.mark.parametrize(("k", "n"), [(1, 10), (3, 50), (5, 200), (40, 1000), (9, 10)])
def test_cp_upper_matches_beta_quantile(k: int, n: int) -> None:
    stats = pytest.importorskip("scipy.stats")
    expected = float(stats.beta.ppf(0.95, k + 1, n - k))
    assert clopper_pearson_upper(k, n, 0.95) == pytest.approx(expected, abs=1e-7)


def test_cp_upper_known_values() -> None:
    # Reference values: Beta(k+1, n-k) 95% quantile.
    assert clopper_pearson_upper(1, 10) == pytest.approx(0.394163, abs=1e-5)
    assert clopper_pearson_upper(3, 50) == pytest.approx(0.147837, abs=1e-5)


def test_cp_upper_degenerate_cases() -> None:
    assert clopper_pearson_upper(0, 0) == 1.0
    assert clopper_pearson_upper(5, 5) == 1.0
    with pytest.raises(ValueError):
        clopper_pearson_upper(1, 10, confidence=1.0)


def test_cp_upper_is_monotone() -> None:
    assert clopper_pearson_upper(2, 100) < clopper_pearson_upper(3, 100)
    assert clopper_pearson_upper(2, 200) < clopper_pearson_upper(2, 100)
    assert clopper_pearson_upper(2, 100, 0.99) > clopper_pearson_upper(2, 100, 0.95)
    assert clopper_pearson_upper(3, 100) > 3 / 100


def test_percentile_linear_interpolation() -> None:
    values = [10.0, 20.0, 30.0, 40.0]
    assert percentile(values, 50) == pytest.approx(25.0)
    assert percentile(values, 90) == pytest.approx(37.0)
    assert percentile([5.0], 90) == 5.0
    assert percentile([], 50) is None


def test_binary_metrics_counts_and_scores() -> None:
    gold = [True, True, True, False, False, False]
    pred = [True, True, False, True, False, False]
    m = binary_metrics(gold, pred)
    assert (m.tp, m.fp, m.fn, m.tn) == (2, 1, 1, 2)
    assert m.precision == pytest.approx(2 / 3)
    assert m.recall == pytest.approx(2 / 3)
    assert m.f1 == pytest.approx(2 / 3)


def test_binary_metrics_no_positive_predictions() -> None:
    m = binary_metrics([True, False], [False, False])
    assert m.precision is None
    assert m.recall == 0.0
    assert m.f1 is None


def test_macro_f1_hand_computed() -> None:
    gold = ["a", "a", "b", "b", "c"]
    pred = ["a", "b", "b", "b", "a"]
    scores = per_class_f1(gold, pred)
    # a: tp1 fp1 fn1 -> 0.5; b: tp2 fp1 fn0 -> 0.8; c: tp0 -> 0
    assert scores == pytest.approx({"a": 0.5, "b": 0.8, "c": 0.0})
    assert macro_f1(gold, pred) == pytest.approx((0.5 + 0.8 + 0.0) / 3)


def test_macro_f1_includes_predicted_only_labels() -> None:
    # A label never in gold but predicted counts (F1 = 0), like sklearn.
    assert macro_f1(["a", "a"], ["a", "z"]) == pytest.approx((2 / 3 + 0.0) / 2)


def test_macro_f1_matches_sklearn_when_available() -> None:
    metrics = pytest.importorskip("sklearn.metrics")
    gold = ["s", "p", "n", "c", "r", "s", "n", "c", "s", "r"]
    pred = ["s", "s", "n", "n", "r", "s", "c", "c", "p", "n"]
    assert macro_f1(gold, pred) == pytest.approx(
        metrics.f1_score(gold, pred, average="macro"))


def test_accuracy() -> None:
    assert accuracy(["a", "b", "c"], ["a", "x", "c"]) == pytest.approx(2 / 3)
    assert accuracy([], []) is None
