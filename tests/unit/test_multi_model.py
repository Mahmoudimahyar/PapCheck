"""Tests for multi-model client (all LLM calls mocked)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from refcheck.llm.cost_tracker import CostTracker
from refcheck.llm.model_registry import ModelConfig
from refcheck.llm.multi_model import call_model, call_models_parallel


def _make_model(alias: str = "test", tier: int = 0) -> ModelConfig:
    return ModelConfig(
        alias=alias, name=f"Test {alias}", abbreviation="TT",
        litellm_id=f"test/{alias}", tier=tier,
        input_cost_per_m=1.0, output_cost_per_m=2.0,
        max_context=128_000, provider="test", env_key="TEST_KEY",
    )


def _mock_response(content: str = '{"verdict":"supported"}') -> SimpleNamespace:
    """Create a mock litellm response object."""
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    usage = SimpleNamespace(prompt_tokens=100, completion_tokens=50)
    return SimpleNamespace(choices=[choice], usage=usage)


class TestCallModel:
    """Test single model calls."""

    @pytest.mark.asyncio
    async def test_successful_call_returns_response(self) -> None:
        model = _make_model()
        mock_resp = _mock_response('{"verdict":"supported","confidence":0.9}')

        with patch("refcheck.llm.multi_model._sync_completion", return_value=mock_resp):
            result = await call_model(model, "test prompt")

        assert result.content == '{"verdict":"supported","confidence":0.9}'
        assert result.parsed is not None
        assert result.parsed["verdict"] == "supported"
        assert result.input_tokens == 100
        assert result.output_tokens == 50

    @pytest.mark.asyncio
    async def test_cost_tracker_records_call(self) -> None:
        model = _make_model()
        tracker = CostTracker()
        mock_resp = _mock_response()

        with patch("refcheck.llm.multi_model._sync_completion", return_value=mock_resp):
            await call_model(model, "test", cost_tracker=tracker, task="verify")

        assert tracker.total_calls == 1
        assert tracker.records[0].task == "verify"

    @pytest.mark.asyncio
    async def test_non_json_response_parsed_is_none(self) -> None:
        model = _make_model()
        mock_resp = _mock_response("I don't know how to do JSON")

        with patch("refcheck.llm.multi_model._sync_completion", return_value=mock_resp):
            result = await call_model(model, "test")

        assert result.parsed is None
        assert result.content == "I don't know how to do JSON"

    @pytest.mark.asyncio
    async def test_system_prompt_included(self) -> None:
        model = _make_model()
        mock_resp = _mock_response()
        captured_messages: list[list[dict[str, str]]] = []

        def capture_completion(
            model_id: str,
            messages: list[dict[str, str]],
            timeout: int,
            max_tokens: int,
        ) -> SimpleNamespace:
            captured_messages.append(messages)
            return mock_resp

        with patch("refcheck.llm.multi_model._sync_completion", side_effect=capture_completion):
            await call_model(model, "user msg", system_prompt="sys msg")

        assert captured_messages[0][0]["role"] == "system"
        assert captured_messages[0][0]["content"] == "sys msg"


class TestCallModelsParallel:
    """Test parallel multi-model calls."""

    @pytest.mark.asyncio
    async def test_parallel_returns_all_results(self) -> None:
        models = [_make_model(f"m{i}") for i in range(3)]
        mock_resp = _mock_response()

        with patch("refcheck.llm.multi_model._sync_completion", return_value=mock_resp):
            results = await call_models_parallel(models, "test prompt")

        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_failed_model_excluded_gracefully(self) -> None:
        models = [_make_model(f"m{i}") for i in range(3)]
        mock_resp = _mock_response()
        call_count = 0

        def flaky_completion(
            model_id: str,
            messages: list[dict[str, str]],
            timeout: int,
            max_tokens: int,
        ) -> SimpleNamespace:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise TimeoutError("Model timed out")
            return mock_resp

        with patch(
            "refcheck.llm.multi_model._sync_completion",
            side_effect=flaky_completion,
        ):
            results = await call_models_parallel(models, "test")

        # 1 failed, 2 succeeded
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_all_fail_returns_empty(self) -> None:
        models = [_make_model(f"m{i}") for i in range(3)]

        with patch(
            "refcheck.llm.multi_model._sync_completion",
            side_effect=RuntimeError("broken"),
        ):
            results = await call_models_parallel(models, "test")

        assert len(results) == 0
