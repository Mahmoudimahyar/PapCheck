"""A refusal / content filter falls back to a model of a DIFFERENT family."""

import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from refcheck.llm.client import call_llm_raw
from refcheck.llm.errors import LLMRefusalError
from refcheck.llm.roles import unavailable_models
from tests.unit.llm_fakes import chat_response, isolated_llm_env

_PATCH = "refcheck.llm.completion._sync_completion"
_GOOD = json.dumps({"summary": "ok", "confidence": 0.9})


class _Out(BaseModel):
    summary: str
    confidence: float


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    yield from isolated_llm_env(monkeypatch, tmp_path)


def _models_called(mock: MagicMock) -> list[str]:
    return [str(c.args[0]["model"]) for c in mock.call_args_list]


async def test_judge_refusal_falls_back_to_other_provider() -> None:
    refused = chat_response("", finish="content_filter", refusal="content filter")
    mock = MagicMock(side_effect=[refused, chat_response(_GOOD)])
    with patch(_PATCH, mock):
        result = await call_llm_raw("test_prompt", {"topic": "r"}, _Out,
                                    role="judge", use_cache=False, max_retries=0)
    # default judge chain: claude-sonnet-5-5 refused -> gpt-6.1-sol answers
    assert result.model_id == "gpt-6.1-sol"
    assert _models_called(mock) == ["anthropic/claude-sonnet-5-5", "openai/gpt-6.1-sol"]
    # a refusal is content-specific: the model stays available for other pairs
    assert "claude-sonnet-5-5" not in unavailable_models()


async def test_refusal_skips_every_candidate_of_the_same_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REFCHECK_JUDGE_MODEL", "claude-sonnet-5-5,claude-opus-5-5,gpt-6.1-sol")
    refused = chat_response("", finish="content_filter", refusal="content filter")
    mock = MagicMock(side_effect=[refused, chat_response(_GOOD)])
    with patch(_PATCH, mock):
        result = await call_llm_raw("test_prompt", {"topic": "r"}, _Out,
                                    role="judge", use_cache=False, max_retries=0)
    # sonnet refused -> opus (same family) is skipped -> gpt-6.1-sol answers
    assert result.model_id == "gpt-6.1-sol"
    assert _models_called(mock) == ["anthropic/claude-sonnet-5-5", "openai/gpt-6.1-sol"]


async def test_refusal_with_no_other_family_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    refused = chat_response("", finish="content_filter", refusal="content filter")
    with patch(_PATCH, MagicMock(return_value=refused)), pytest.raises(LLMRefusalError):
        await call_llm_raw("test_prompt", {"topic": "r"}, _Out, model="claude-opus-5-5",
                           role="judge", use_cache=False, max_retries=0)
    # anthropic_only: the whole judge chain is one family, so the refusal surfaces
    monkeypatch.setenv("REFCHECK_PRIVACY_PROFILE", "anthropic_only")
    mock = MagicMock(return_value=refused)
    with patch(_PATCH, mock), pytest.raises(LLMRefusalError):
        await call_llm_raw("test_prompt", {"topic": "r2"}, _Out, role="judge",
                           use_cache=False, max_retries=0)
    assert mock.call_count == 1
