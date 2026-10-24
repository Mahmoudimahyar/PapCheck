"""Cost tracking for V5 specs: cached tokens, budgets, role summaries."""

from types import SimpleNamespace

import pytest

from refcheck.llm.cost_tracker import CostLimitExceededError, CostTracker
from refcheck.llm.model_registry import REGISTRY
from refcheck.llm.usage import TokenUsage, compute_cost, usage_from_response


class TestComputeCost:
    def test_anthropic_cache_read_and_write(self) -> None:
        sonnet = REGISTRY["claude-sonnet-5-5"]
        usage = TokenUsage(input_tokens=10_000, cached_input_tokens=6_000,
                           cache_write_tokens=3_000, output_tokens=1_000)
        expected = (1_000 * 2.0 + 6_000 * 0.10 + 3_000 * 2.5 + 1_000 * 10.0) / 1e6
        assert compute_cost(sonnet, usage) == pytest.approx(expected)

    def test_decisions_cached_tokens_billed_as_input(self) -> None:
        spec = REGISTRY["gpt-6-luna-decisions"]
        usage = TokenUsage(input_tokens=4_000, cached_input_tokens=3_000)
        assert compute_cost(spec, usage) == pytest.approx(4_000 * 0.10 / 1e6)

    def test_inconsistent_counts_never_go_negative(self) -> None:
        usage = TokenUsage(input_tokens=100, cached_input_tokens=500, cache_write_tokens=50)
        assert compute_cost(REGISTRY["claude-haiku-5-5"], usage) >= 0


class TestUsageExtraction:
    def test_openai_shape(self) -> None:
        response = SimpleNamespace(usage=SimpleNamespace(
            prompt_tokens=4_033, completion_tokens=300,
            prompt_tokens_details=SimpleNamespace(cached_tokens=4_012),
            completion_tokens_details=SimpleNamespace(reasoning_tokens=150),
        ))
        usage = usage_from_response(response)
        assert usage.input_tokens == 4_033 and usage.cached_input_tokens == 4_012
        assert usage.reasoning_tokens == 150 and usage.cache_write_tokens == 0

    def test_anthropic_shape(self) -> None:
        response = SimpleNamespace(usage=SimpleNamespace(
            prompt_tokens=7_320, completion_tokens=40, cache_read_input_tokens=7_293,
            cache_creation_input_tokens=0, prompt_tokens_details=None,
        ))
        usage = usage_from_response(response)
        assert usage.cached_input_tokens == 7_293

    def test_missing_usage(self) -> None:
        assert usage_from_response(SimpleNamespace()) == TokenUsage()


class TestTracker:
    def test_record_usage_and_summary(self) -> None:
        tracker = CostTracker()
        tracker.record_usage(REGISTRY["gpt-6-luna"], TokenUsage(input_tokens=1_000,
                                                                output_tokens=100),
                             "verify", role="verifier", response_time_ms=900)
        tracker.record_usage(REGISTRY["claude-sonnet-5-5"], TokenUsage(input_tokens=2_000),
                             "judge", role="judge")
        tracker.record_usage(REGISTRY["claude-sonnet-5-5"], TokenUsage(), "judge",
                             role="judge", success=False)
        summary = tracker.summary()
        assert summary.total_calls == 3 and summary.failed_calls == 1
        assert summary.calls_by_role == {"verifier": 1, "judge": 2}
        assert summary.by_role["judge"] == pytest.approx(2_000 * 2.0 / 1e6)
        assert summary.total_input_tokens == 3_000
        assert "claude-sonnet-5-5" in summary.by_model

    def test_record_usage_never_raises_but_ensure_budget_does(self) -> None:
        tracker = CostTracker(max_cost=0.001)
        tracker.record_usage(REGISTRY["claude-opus-5-5"],
                             TokenUsage(input_tokens=1_000_000), "judge")
        with pytest.raises(CostLimitExceededError):
            tracker.ensure_budget()

    def test_ensure_budget_passes_under_limit(self) -> None:
        CostTracker(max_cost=1.0).ensure_budget()

    def test_legacy_record_accepts_model_spec(self) -> None:
        tracker = CostTracker()
        entry = tracker.record(REGISTRY["gpt-6-luna"], 1_000_000, 0, "x")
        assert entry.cost_usd == pytest.approx(0.10)
        assert entry.model_name == "gpt-6-luna"


def test_max_cost_from_env(monkeypatch: "pytest.MonkeyPatch") -> None:
    from refcheck.llm.cost_tracker import CostTracker

    monkeypatch.setenv("REFCHECK_MAX_COST_USD", "1.5")
    assert CostTracker().max_cost == 1.5
    assert CostTracker(max_cost=3.0).max_cost == 3.0
    monkeypatch.setenv("REFCHECK_MAX_COST_USD", "not-a-number")
    assert CostTracker().max_cost == 50.0
