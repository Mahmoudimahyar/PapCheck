"""call_llm cache breakpoints and cost tracking (litellm mocked)."""

import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from refcheck.llm.client import call_llm, call_llm_raw
from refcheck.llm.cost_tracker import CostLimitExceededError, CostTracker
from refcheck.llm.errors import LLMCallError
from tests.unit.llm_fakes import chat_response, isolated_llm_env, not_found_error

_PATCH = "refcheck.llm.completion._sync_completion"
_GOOD = json.dumps({"summary": "Test summary", "confidence": 0.85})


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    yield from isolated_llm_env(monkeypatch, tmp_path)


class MockLLMOutput(BaseModel):
    """Test output model for LLM calls."""

    summary: str
    confidence: float


def _kwargs(mock: MagicMock, call: int = 0) -> dict[str, object]:
    kwargs: dict[str, object] = mock.call_args_list[call].args[0]
    return kwargs


class TestCachingBreakpoints:
    async def test_anthropic_system_prefix_gets_cache_control(self) -> None:
        mock = MagicMock(return_value=chat_response(_GOOD))
        with patch(_PATCH, mock):
            await call_llm("test_prompt", {"topic": "a"}, MockLLMOutput, role="judge",
                           use_cache=False, system_template="test_prompt",
                           system_variables={"topic": "stable"})
        messages = _kwargs(mock)["messages"]
        assert isinstance(messages, list)
        system = messages[0]
        assert system["role"] == "system"
        assert system["content"][0]["cache_control"] == {"type": "ephemeral"}
        assert isinstance(messages[1]["content"], str)

    async def test_openai_gets_plain_strings(self) -> None:
        mock = MagicMock(return_value=chat_response(_GOOD))
        with patch(_PATCH, mock):
            await call_llm("test_prompt", {"topic": "o"}, MockLLMOutput, use_cache=False,
                           system_template="test_prompt", system_variables={"topic": "s"})
        messages = _kwargs(mock)["messages"]
        assert isinstance(messages, list)
        assert all(isinstance(m["content"], str) for m in messages)


class TestCostTracking:
    async def test_cost_recorded_with_cached_tokens(self) -> None:
        tracker = CostTracker()
        response = chat_response(_GOOD, prompt_tokens=10_000, completion_tokens=500,
                                 cached=8_000)
        with patch(_PATCH, MagicMock(return_value=response)):
            result = await call_llm_raw("test_prompt", {"topic": "c"}, MockLLMOutput,
                                        role="confirm", use_cache=False,
                                        cost_tracker=tracker, task="confirm")
        # confirm resolves to gpt-6-luna: $0.10/M input, $0.01/M cached, $0.50/M output
        assert result.model_id == "gpt-6-luna"
        expected = (2_000 * 0.10 + 8_000 * 0.01 + 500 * 0.50) / 1e6
        assert result.cost_usd == pytest.approx(expected)
        record = tracker.records[0]
        assert record.role == "confirm" and record.cached_input_tokens == 8_000
        assert tracker.summary().by_role["confirm"] == pytest.approx(expected, abs=1e-6)

    async def test_failed_call_is_recorded(self) -> None:
        tracker = CostTracker()
        with patch(_PATCH, MagicMock(side_effect=not_found_error())), \
                pytest.raises(LLMCallError):
            await call_llm("test_prompt", {"topic": "f"}, MockLLMOutput, model="gpt-6-luna",
                           use_cache=False, cost_tracker=tracker)
        assert tracker.summary().failed_calls == 1

    async def test_budget_checked_before_call(self) -> None:
        tracker = CostTracker(max_cost=0.0)
        mock = MagicMock(return_value=chat_response(_GOOD))
        with patch(_PATCH, mock), pytest.raises(CostLimitExceededError):
            await call_llm("test_prompt", {"topic": "b"}, MockLLMOutput, use_cache=False,
                           cost_tracker=tracker)
        mock.assert_not_called()
