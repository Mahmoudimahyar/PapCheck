"""Text embeddings via litellm.embedding (sync in a thread), cached on disk.

Vectors are cached by sha256(model + dimensions + text). Vectors from
different models are NOT comparable (3-small: 1536 dims; the 3-large
fallback is requested at 1024 dims) — callers that persist vectors should
key them by ``EmbeddingResult.model``.
"""

import logging
import time
from collections.abc import Sequence

import litellm
from pydantic import BaseModel, Field

from refcheck.llm.cache import get_vector, make_key, set_vector
from refcheck.llm.cost_tracker import CostTracker
from refcheck.llm.degraded_guard import note_soft_failure
from refcheck.llm.errors import LLMCallError, LLMError
from refcheck.llm.model_lookup import spec_for
from refcheck.llm.model_spec import ModelSpec
from refcheck.llm.retry import call_provider
from refcheck.llm.roles import mark_unavailable, resolve_role
from refcheck.llm.usage import TokenUsage, usage_from_response

logger = logging.getLogger(__name__)

__all__ = ["EmbeddingError", "EmbeddingResult", "embed", "embed_with_model"]

_BATCH_SIZE = 128
_BATCH_CHARS = 400_000  # ~100K tokens, well under the 300K/request limit
_MAX_TEXT_CHARS = 24_000  # ~6K tokens; the model limit is 8,191 tokens
_DEFAULT_TIMEOUT_S = 30.0


class EmbeddingError(LLMError):
    """Embedding call failed or no embedding model is available."""


class EmbeddingResult(BaseModel):
    """Vectors (same order as the input) and the model that produced them."""

    model: str
    vectors: list[list[float]] = Field(default_factory=list)
    input_tokens: int = 0
    cached_count: int = 0


def _sync_embedding(kwargs: dict[str, object]) -> object:
    """Blocking litellm call (patched in tests)."""
    response: object = litellm.embedding(**kwargs)  # type: ignore[call-overload]
    return response


def _vectors(response: object) -> list[list[float]]:
    data = list(getattr(response, "data", None) or [])

    def field(item: object, name: str) -> object:
        return item.get(name) if isinstance(item, dict) else getattr(item, name, None)

    data.sort(key=lambda item: int(str(field(item, "index") or 0)))
    out: list[list[float]] = []
    for item in data:
        vector = field(item, "embedding")
        if not isinstance(vector, list):
            raise ValueError("embedding response item without a vector")
        out.append([float(x) for x in vector])
    return out


def _batches(indices: list[int], texts: list[str]) -> list[list[int]]:
    batches: list[list[int]] = []
    current: list[int] = []
    chars = 0
    for i in indices:
        if current and (len(current) >= _BATCH_SIZE or chars + len(texts[i]) > _BATCH_CHARS):
            batches.append(current)
            current, chars = [], 0
        current.append(i)
        chars += len(texts[i])
    if current:
        batches.append(current)
    return batches


async def _embed_batch(spec: ModelSpec, batch: list[str], cost_tracker: CostTracker | None,
                       task: str) -> tuple[list[list[float]], int]:
    kwargs: dict[str, object] = {"model": spec.litellm_id, "input": batch}
    if spec.dimensions:
        kwargs["dimensions"] = spec.dimensions

    def run(api_key: str, timeout: float) -> object:
        return _sync_embedding({**kwargs, "api_key": api_key, "timeout": timeout})

    start = time.perf_counter()
    response = await call_provider(run, provider=spec.provider, label=spec.id,
                                   timeout=spec.timeout_s or _DEFAULT_TIMEOUT_S)
    vectors = _vectors(response)
    if len(vectors) != len(batch):
        raise ValueError(f"expected {len(batch)} vectors, got {len(vectors)}")
    usage = usage_from_response(response)
    if cost_tracker is not None:
        latency = int((time.perf_counter() - start) * 1000)
        cost_tracker.record_usage(spec, TokenUsage(input_tokens=usage.input_tokens), task,
                                  "embedding", latency)
    return vectors, usage.input_tokens


async def embed_with_model(
    texts: Sequence[str],
    *,
    model: str | None = None,
    cost_tracker: CostTracker | None = None,
    task: str = "embedding",
    use_cache: bool = True,
) -> EmbeddingResult:
    """Embed texts with the embedding role's model (or ``model``).

    V5.8: a role-resolved call that fails with an outage is recorded as a degraded
    embedding role (callers fall back to BM25-only retrieval).
    """
    try:
        return await _embed(texts, model, cost_tracker, task, use_cache)
    except EmbeddingError as exc:
        if model is None:
            note_soft_failure("embedding", exc.model_id, exc.kind, str(exc)[:200],
                              cost_tracker)
        raise


async def _embed(texts: Sequence[str], model: str | None, cost_tracker: CostTracker | None,
                 task: str, use_cache: bool) -> EmbeddingResult:
    spec = spec_for(model, "embedding") if model else resolve_role("embedding")
    if spec is None or spec.kind != "embedding":
        raise EmbeddingError("no embedding model available", "unavailable")
    clean = [(t or " ")[:_MAX_TEXT_CHARS] for t in texts]
    keys = [make_key("emb", {"m": spec.litellm_id, "d": spec.dimensions, "t": t}) for t in clean]
    vectors: list[list[float] | None] = [get_vector(k) if use_cache else None for k in keys]
    positions: dict[str, list[int]] = {}  # identical texts are embedded once
    for i, v in enumerate(vectors):
        if v is None:
            positions.setdefault(keys[i], []).append(i)
    missing = [idx[0] for idx in positions.values()]
    result = EmbeddingResult(model=spec.id, cached_count=sum(v is not None for v in vectors))
    if missing and cost_tracker is not None:
        cost_tracker.ensure_budget()
    for batch in _batches(missing, clean):
        try:
            batch_vectors, tokens = await _embed_batch(
                spec, [clean[i] for i in batch], cost_tracker, task)
        except LLMCallError as exc:
            if exc.is_hard:
                mark_unavailable(spec.id, f"{exc.kind}: {exc}")
            raise EmbeddingError(str(exc), exc.kind, spec.id) from exc
        except (ValueError, TypeError) as exc:
            raise EmbeddingError(f"bad embedding response: {exc}", "invalid_output",
                                 spec.id) from exc
        result.input_tokens += tokens
        for i, vector in zip(batch, batch_vectors, strict=True):
            if use_cache:
                set_vector(keys[i], vector)
            for j in positions[keys[i]]:
                vectors[j] = vector
    result.vectors = [v for v in vectors if v is not None]
    return result


async def embed(
    texts: list[str],
    *,
    model: str | None = None,
    cost_tracker: CostTracker | None = None,
    task: str = "embedding",
    use_cache: bool = True,
) -> list[list[float]]:
    """Embed texts; same order as input. Raises EmbeddingError on failure."""
    result = await embed_with_model(texts, model=model, cost_tracker=cost_tracker,
                                    task=task, use_cache=use_cache)
    return result.vectors
