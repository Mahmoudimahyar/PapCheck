"""Embeddings: batching, disk cache, dedupe, errors, cost."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from refcheck.llm import embeddings
from refcheck.llm.cost_tracker import CostTracker
from refcheck.llm.embeddings import EmbeddingError, embed, embed_with_model
from tests.unit.llm_fakes import (
    FAKE_OPENAI,
    embedding_response,
    isolated_llm_env,
    not_found_error,
)

_PATCH = "refcheck.llm.embeddings._sync_embedding"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    yield from isolated_llm_env(monkeypatch, tmp_path)


def _fake(kwargs: dict[str, object]) -> object:
    """One deterministic 3-d vector per input text."""
    texts = kwargs["input"]
    assert isinstance(texts, list)
    return embedding_response([[float(len(t)), 1.0, 0.5] for t in texts], tokens=5 * len(texts))


class TestEmbed:
    async def test_order_model_and_request(self) -> None:
        mock = MagicMock(side_effect=_fake)
        with patch(_PATCH, mock):
            vectors = await embed(["a", "bbb", "cc"])
        assert [v[0] for v in vectors] == [1.0, 3.0, 2.0]  # response order is shuffled
        kwargs = mock.call_args.args[0]
        assert kwargs["model"] == "openai/text-embedding-3-small"
        assert kwargs["api_key"] == FAKE_OPENAI
        assert "dimensions" not in kwargs

    async def test_cache_hit_and_dedupe(self) -> None:
        mock = MagicMock(side_effect=_fake)
        with patch(_PATCH, mock):
            first = await embed_with_model(["same", "same", "other"])
            second = await embed_with_model(["same", "new"])
        assert first.vectors[0] == first.vectors[1]
        assert len(mock.call_args_list[0].args[0]["input"]) == 2  # duplicates embedded once
        assert second.cached_count == 1
        assert mock.call_args_list[1].args[0]["input"] == ["new"]

    async def test_cache_can_be_bypassed(self) -> None:
        mock = MagicMock(side_effect=_fake)
        with patch(_PATCH, mock):
            await embed(["x"], use_cache=False)
            await embed(["x"], use_cache=False)
        assert mock.call_count == 2

    async def test_batching(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(embeddings, "_BATCH_SIZE", 4)
        mock = MagicMock(side_effect=_fake)
        with patch(_PATCH, mock):
            vectors = await embed([f"text {i}" for i in range(10)])
        assert len(vectors) == 10
        assert [len(c.args[0]["input"]) for c in mock.call_args_list] == [4, 4, 2]

    async def test_fallback_model_sends_dimensions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REFCHECK_EMBEDDING_MODEL", "text-embedding-3-large")
        mock = MagicMock(side_effect=_fake)
        with patch(_PATCH, mock):
            result = await embed_with_model(["x"])
        assert mock.call_args.args[0]["dimensions"] == 1024
        assert result.model == "text-embedding-3-large"

    async def test_cost_tracked(self) -> None:
        tracker = CostTracker()
        with patch(_PATCH, MagicMock(side_effect=_fake)):
            await embed(["a", "b"], cost_tracker=tracker)
        record = tracker.records[0]
        assert record.role == "embedding" and record.input_tokens == 10
        assert record.cost_usd == pytest.approx(10 * 0.02 / 1e6)


class TestErrors:
    async def test_api_failure_raises_embedding_error(self) -> None:
        with patch(_PATCH, MagicMock(side_effect=not_found_error())), \
                pytest.raises(EmbeddingError) as info:
            await embed(["x"])
        assert info.value.kind == "not_found"

    async def test_wrong_vector_count(self) -> None:
        with patch(_PATCH, MagicMock(return_value=embedding_response([[1.0]]))), \
                pytest.raises(EmbeddingError):
            await embed(["a", "b"])

    async def test_no_embedding_model_under_anthropic_only(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("REFCHECK_PRIVACY_PROFILE", "anthropic_only")
        with pytest.raises(EmbeddingError) as info:
            await embed(["x"])
        assert info.value.kind == "unavailable"
