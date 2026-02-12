"""Unit tests for LLM client (mocked — no real API calls)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from refcheck.llm.templates import render_template


class MockLLMOutput(BaseModel):
    """Test output model for LLM calls."""

    summary: str
    confidence: float


class TestTemplateLoading:
    def test_render_template(self) -> None:
        """Templates render with variables."""
        result = render_template("test_prompt", {"topic": "cancer research"})
        assert "cancer research" in result

    def test_missing_template_raises(self) -> None:
        """Missing templates raise an error."""
        from jinja2 import TemplateNotFound

        with pytest.raises(TemplateNotFound):
            render_template("nonexistent_template", {})


class TestCallLLM:
    @pytest.mark.asyncio
    async def test_successful_call(self) -> None:
        """call_llm validates output against Pydantic model."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "summary": "Test summary",
            "confidence": 0.85,
        })

        with patch("refcheck.llm.client.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)

            from refcheck.llm.client import call_llm

            result = await call_llm(
                template="test_prompt",
                variables={"topic": "testing"},
                output_model=MockLLMOutput,
            )
            assert result.summary == "Test summary"
            assert result.confidence == 0.85

    @pytest.mark.asyncio
    async def test_retry_on_invalid_json(self) -> None:
        """call_llm retries on malformed JSON."""
        bad_response = MagicMock()
        bad_response.choices = [MagicMock()]
        bad_response.choices[0].message.content = "not json"

        good_response = MagicMock()
        good_response.choices = [MagicMock()]
        good_response.choices[0].message.content = json.dumps({
            "summary": "Retried",
            "confidence": 0.5,
        })

        with patch("refcheck.llm.client.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=[bad_response, good_response]
            )

            from refcheck.llm.client import call_llm

            result = await call_llm(
                template="test_prompt",
                variables={"topic": "test"},
                output_model=MockLLMOutput,
                max_retries=1,
            )
            assert result.summary == "Retried"

    @pytest.mark.asyncio
    async def test_fails_after_retries_exhausted(self) -> None:
        """call_llm raises after all retries fail."""
        bad_response = MagicMock()
        bad_response.choices = [MagicMock()]
        bad_response.choices[0].message.content = "not json"

        with patch("refcheck.llm.client.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=bad_response)

            from refcheck.llm.client import LLMResponseInvalidError, call_llm

            with pytest.raises(LLMResponseInvalidError):
                await call_llm(
                    template="test_prompt",
                    variables={"topic": "test"},
                    output_model=MockLLMOutput,
                    max_retries=1,
                )
