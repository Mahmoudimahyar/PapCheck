"""Tests for cost tracker."""

import pytest

from refcheck.llm.cost_tracker import CostLimitExceededError, CostTracker
from refcheck.llm.model_registry import ModelConfig


def _make_model(
    name: str = "Test Model",
    input_cost: float = 1.0,
    output_cost: float = 2.0,
    tier: int = 0,
) -> ModelConfig:
    return ModelConfig(
        alias="test", name=name, abbreviation="TM",
        litellm_id="test/model", tier=tier,
        input_cost_per_m=input_cost, output_cost_per_m=output_cost,
        max_context=128_000, provider="test", env_key="TEST_KEY",
    )


class TestCostMath:
    """Verify cost calculation is correct."""

    def test_cost_with_known_values(self) -> None:
        tracker = CostTracker(max_cost=100.0)
        model = _make_model(input_cost=3.0, output_cost=15.0)

        # 1000 input tokens, 500 output tokens
        record = tracker.record(model, 1000, 500, "test_task")
        # 1000/1M * 3.0 = 0.003, 500/1M * 15.0 = 0.0075
        expected = 0.003 + 0.0075
        assert abs(record.cost_usd - expected) < 1e-6

    def test_free_tier_zero_cost(self) -> None:
        tracker = CostTracker()
        model = _make_model(input_cost=0.0, output_cost=0.0)
        record = tracker.record(model, 10000, 5000, "verify")
        assert record.cost_usd == 0.0

    def test_total_cost_accumulates(self) -> None:
        tracker = CostTracker()
        model = _make_model(input_cost=1.0, output_cost=1.0)
        # 3 calls at 1000 tokens each
        for _ in range(3):
            tracker.record(model, 1000, 1000, "task")
        # Each: 0.001 + 0.001 = 0.002, total = 0.006
        assert abs(tracker.total_cost - 0.006) < 1e-6


class TestCostLimit:
    """Test cost limit enforcement."""

    def test_limit_triggers_exception(self) -> None:
        tracker = CostTracker(max_cost=0.01)
        model = _make_model(input_cost=100.0, output_cost=100.0)
        with pytest.raises(CostLimitExceededError):
            # 1M tokens * $100/M = $100 > $0.01
            tracker.record(model, 1_000_000, 1_000_000, "expensive")

    def test_under_limit_no_exception(self) -> None:
        tracker = CostTracker(max_cost=100.0)
        model = _make_model(input_cost=1.0, output_cost=1.0)
        tracker.record(model, 1000, 1000, "cheap")
        assert tracker.total_cost < 100.0


class TestCostSummary:
    """Test summary aggregation."""

    def test_summary_by_model(self) -> None:
        tracker = CostTracker()
        m1 = _make_model(name="Model A", input_cost=1.0, output_cost=1.0)
        m2 = _make_model(name="Model B", input_cost=2.0, output_cost=2.0)
        tracker.record(m1, 1000, 1000, "task1")
        tracker.record(m2, 1000, 1000, "task2")

        summary = tracker.summary()
        assert "Model A" in summary.by_model
        assert "Model B" in summary.by_model

    def test_summary_by_tier(self) -> None:
        tracker = CostTracker()
        m0 = _make_model(tier=0)
        m1 = _make_model(tier=1)
        tracker.record(m0, 100, 100, "t0")
        tracker.record(m0, 100, 100, "t0")
        tracker.record(m1, 100, 100, "t1")

        summary = tracker.summary()
        assert summary.by_tier[0] == 2
        assert summary.by_tier[1] == 1

    def test_summary_total_calls(self) -> None:
        tracker = CostTracker()
        model = _make_model()
        for _ in range(5):
            tracker.record(model, 100, 100, "task")
        summary = tracker.summary()
        assert summary.total_calls == 5

    def test_empty_tracker_summary(self) -> None:
        tracker = CostTracker()
        summary = tracker.summary()
        assert summary.total_usd == 0.0
        assert summary.total_calls == 0
