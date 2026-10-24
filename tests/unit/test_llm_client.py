"""call_llm / call_llm_raw with litellm mocked (no real API calls)."""

import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from refcheck.llm.client import call_llm, call_llm_raw
from refcheck.llm.errors import (
    LLMCallError,
    LLMRefusalError,
    LLMResponseInvalidError,
    NoModelAvailableError,
)
from refcheck.llm.roles import unavailable_models
from refcheck.llm.templates import render_template
from tests.unit.llm_fakes import (
    FAKE_ANTH_BACKUP,
    FAKE_OPENAI,
    billing_error,
    chat_response,
    isolated_llm_env,
    not_found_error,
    rate_limit_error,
)

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


class TestTemplateLoading:
    def test_render_template(self) -> None:
        assert "cancer research" in render_template("test_prompt", {"topic": "cancer research"})

    def test_missing_template_raises(self) -> None:
        from jinja2 import TemplateNotFound

        with pytest.raises(TemplateNotFound):
            render_template("nonexistent_template", {})


class TestCallLLM:
    async def test_successful_call_and_request_shape(self) -> None:
        mock = MagicMock(return_value=chat_response(_GOOD))
        with patch(_PATCH, mock):
            result = await call_llm("test_prompt", {"topic": "testing"}, MockLLMOutput,
                                    use_cache=False)
        assert result.summary == "Test summary" and result.confidence == 0.85
        kwargs = _kwargs(mock)
        assert kwargs["model"] == "openai/gpt-6-luna"  # utility role default
        assert kwargs["api_key"] == FAKE_OPENAI
        assert kwargs["reasoning_effort"] == "none"
        assert "temperature" not in kwargs
        fmt = kwargs["response_format"]
        assert isinstance(fmt, dict) and fmt["type"] == "json_schema"
        schema_block = fmt["json_schema"]
        assert isinstance(schema_block, dict) and schema_block["strict"] is True

    async def test_retry_on_invalid_json_sends_correction(self) -> None:
        mock = MagicMock(side_effect=[chat_response("not json"), chat_response(_GOOD)])
        with patch(_PATCH, mock):
            result = await call_llm_raw("test_prompt", {"topic": "retry"}, MockLLMOutput,
                                        max_retries=1, use_cache=False)
        assert result.parsed.summary == "Test summary"
        assert result.attempts == 2
        messages = _kwargs(mock, 1)["messages"]
        assert isinstance(messages, list) and len(messages) == 3
        assert messages[1]["role"] == "assistant" and "not json" in messages[1]["content"]

    async def test_fails_after_retries_exhausted(self) -> None:
        mock = MagicMock(return_value=chat_response("not json"))
        with patch(_PATCH, mock), pytest.raises(LLMResponseInvalidError):
            await call_llm("test_prompt", {"topic": "fail"}, MockLLMOutput,
                           max_retries=1, use_cache=False)
        # invalid output falls back: gpt-6-luna (2 attempts) then claude-haiku-5-5 (2)
        assert mock.call_count == 4
        assert _kwargs(mock, 2)["model"] == "anthropic/claude-haiku-5-5"

    async def test_invalid_output_falls_back_to_next_model(self) -> None:
        mock = MagicMock(side_effect=[chat_response("not json")] * 2 + [chat_response(_GOOD)])
        with patch(_PATCH, mock):
            result = await call_llm_raw("test_prompt", {"topic": "inv"}, MockLLMOutput,
                                        max_retries=1, use_cache=False)
        assert result.model_id == "claude-haiku-5-5"
        assert "gpt-6-luna" not in unavailable_models()  # content-specific, not hard

    async def test_refusal_raises(self) -> None:
        mock = MagicMock(return_value=chat_response("", refusal="I can't help with that"))
        with patch(_PATCH, mock), pytest.raises(LLMRefusalError):
            await call_llm("test_prompt", {"topic": "x"}, MockLLMOutput, use_cache=False)
        # each family is asked once: gpt-6-luna refuses, then claude-haiku-5-5 refuses
        assert [_kwargs(mock, i)["model"] for i in range(mock.call_count)] == [
            "openai/gpt-6-luna", "anthropic/claude-haiku-5-5"]

    async def test_truncated_output_doubles_max_tokens(self) -> None:
        mock = MagicMock(side_effect=[chat_response('{"summ', finish="length"),
                                      chat_response(_GOOD)])
        with patch(_PATCH, mock):
            await call_llm("test_prompt", {"topic": "x"}, MockLLMOutput, use_cache=False,
                           max_output_tokens=100)
        assert _kwargs(mock, 0)["max_tokens"] == 100
        assert _kwargs(mock, 1)["max_tokens"] == 200
        assert _kwargs(mock, 1)["messages"] == _kwargs(mock, 0)["messages"]

    async def test_cache_hit_skips_second_call(self) -> None:
        mock = MagicMock(return_value=chat_response(_GOOD))
        with patch(_PATCH, mock):
            await call_llm("test_prompt", {"topic": "cached"}, MockLLMOutput)
            second = await call_llm_raw("test_prompt", {"topic": "cached"}, MockLLMOutput)
        assert mock.call_count == 1
        assert second.from_cache and second.cost_usd == 0.0


class TestModelsAndRoles:
    async def test_judge_role_uses_anthropic_with_effort_and_backup_key(self) -> None:
        mock = MagicMock(side_effect=[billing_error(), chat_response(_GOOD)])
        with patch(_PATCH, mock):
            result = await call_llm_raw("test_prompt", {"topic": "j"}, MockLLMOutput,
                                        role="judge", use_cache=False)
        assert result.model_id == "claude-sonnet-5-5" and result.provider == "anthropic"
        assert _kwargs(mock, 1)["api_key"] == FAKE_ANTH_BACKUP
        assert _kwargs(mock, 1)["reasoning_effort"] == "low"
        assert "temperature" not in _kwargs(mock, 1)

    async def test_hard_failure_falls_back_to_next_model(self) -> None:
        mock = MagicMock(side_effect=[not_found_error(), chat_response(_GOOD)])
        with patch(_PATCH, mock):
            result = await call_llm_raw("test_prompt", {"topic": "fb"}, MockLLMOutput,
                                        role="verifier", use_cache=False)
        assert _kwargs(mock, 0)["model"] == "anthropic/claude-haiku-5-5"
        assert result.model_id == "gpt-6-luna" and result.provider == "openai"
        assert "claude-haiku-5-5" in unavailable_models()
        assert _kwargs(mock, 1)["reasoning_effort"] == "low"

    async def test_exhausted_retries_fall_back_without_disabling(self) -> None:
        mock = MagicMock(side_effect=[rate_limit_error()] * 3 + [chat_response(_GOOD)])
        with patch(_PATCH, mock):
            result = await call_llm_raw("test_prompt", {"topic": "rl"}, MockLLMOutput,
                                        role="utility", use_cache=False)
        assert result.model_id == "claude-haiku-5-5"
        assert "gpt-6-luna" not in unavailable_models()

    async def test_explicit_model_does_not_fall_back(self) -> None:
        with patch(_PATCH, MagicMock(side_effect=not_found_error())), \
                pytest.raises(LLMCallError) as info:
            await call_llm("test_prompt", {"topic": "m"}, MockLLMOutput,
                           model="gpt-6.1-sol", role="confirm", use_cache=False)
        assert info.value.kind == "not_found"

    async def test_explicit_model_gets_role_effort(self) -> None:
        mock = MagicMock(return_value=chat_response(_GOOD))
        with patch(_PATCH, mock):
            await call_llm("test_prompt", {"topic": "m"}, MockLLMOutput,
                           model="gpt-6.1-sol", role="utility", use_cache=False)
        assert _kwargs(mock)["reasoning_effort"] == "low"  # "none" is rejected by sol

    async def test_no_model_left_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REFCHECK_PRIVACY_PROFILE", "anthropic_only")
        mock = MagicMock(side_effect=[billing_error(), billing_error()])
        with patch(_PATCH, mock), pytest.raises(LLMCallError) as info:
            await call_llm("test_prompt", {"topic": "x"}, MockLLMOutput,
                           role="confirm", use_cache=False)
        assert info.value.kind == "billing"  # the real cause, not "unavailable"
        with patch(_PATCH, mock), pytest.raises(NoModelAvailableError):
            await call_llm("test_prompt", {"topic": "y"}, MockLLMOutput,
                           role="confirm", use_cache=False)

    async def test_expired_budget_does_not_cycle_through_fallbacks(self) -> None:
        mock = MagicMock(return_value=chat_response(_GOOD))
        with patch(_PATCH, mock), pytest.raises(LLMCallError) as info:
            await call_llm("test_prompt", {"topic": "t"}, MockLLMOutput, role="judge",
                           use_cache=False, timeout=0.5)
        assert info.value.kind == "timeout"
        mock.assert_not_called()
