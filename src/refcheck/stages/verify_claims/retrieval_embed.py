"""Dense (embedding) ranking of a document's windows, with per-document caching.

Window vectors are computed once per document fingerprint (and shared by
concurrent claims on the same source); the query is embedded per claim.
Any failure returns None so the caller falls back to BM25 only.
"""

import asyncio
import logging
import math
import operator
import os
from array import array
from collections import OrderedDict
from typing import TYPE_CHECKING

from refcheck.stages.verify_claims.source_models import SourceDocument

if TYPE_CHECKING:
    from refcheck.llm.cost_tracker import CostTracker

logger = logging.getLogger(__name__)

_DOC_CACHE_SIZE = 16
_DEFAULT_TIMEOUT_S = 60.0
_vector_cache: "OrderedDict[str, list[array[float]]]" = OrderedDict()
_inflight: "dict[str, asyncio.Task[list[array[float]]]]" = {}
_warned: set[str] = set()


async def embed_texts(
    texts: list[str], cost_tracker: "CostTracker | None" = None,
) -> list[list[float]]:
    """Embed via the LLM layer (imported lazily so BM25 retrieval never depends on it)."""
    from refcheck.llm.embeddings import embed

    return await embed(texts, cost_tracker=cost_tracker, task="retrieval")


def _consume_exception(task: "asyncio.Task[list[array[float]]]") -> None:
    # Awaiters that timed out never read the result; mark the exception retrieved.
    if not task.cancelled():
        task.exception()


def _unit(vector: list[float]) -> "array[float]":
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return array("f", (x / norm for x in vector))


async def _compute(texts: list[str], cost_tracker: "CostTracker | None") -> list["array[float]"]:
    vectors = await embed_texts(texts, cost_tracker)
    if len(vectors) != len(texts):
        raise ValueError(f"expected {len(texts)} vectors, got {len(vectors)}")
    return [_unit(v) for v in vectors]


async def _window_vectors(
    doc: SourceDocument, texts: list[str], cost_tracker: "CostTracker | None",
) -> list["array[float]"]:
    key = doc.fingerprint
    cached = _vector_cache.get(key)
    if cached is not None:
        _vector_cache.move_to_end(key)
        return cached
    loop = asyncio.get_running_loop()
    task = _inflight.get(key)
    if task is None or task.get_loop() is not loop or task.done():
        task = loop.create_task(_compute(texts, cost_tracker))
        task.add_done_callback(_consume_exception)
        _inflight[key] = task
    try:
        # shield: one claim timing out must not cancel the shared document embedding
        vectors = await asyncio.shield(task)
    finally:
        if task.done() and _inflight.get(key) is task:
            _inflight.pop(key, None)
    _vector_cache[key] = vectors
    while len(_vector_cache) > _DOC_CACHE_SIZE:
        _vector_cache.popitem(last=False)
    return vectors


async def embedding_ranking(
    query: str,
    doc: SourceDocument,
    top_n: int,
    cost_tracker: "CostTracker | None" = None,
) -> list[tuple[int, float]] | None:
    """Top-n (chunk idx, cosine) over the document's windows; None on any failure."""
    windows = doc.windows
    if not windows or not query.strip():
        return None
    timeout = float(os.environ.get("REFCHECK_EMBED_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_S))
    try:
        async with asyncio.timeout(timeout):
            doc_vectors = await _window_vectors(doc, [w.text for w in windows], cost_tracker)
            query_vector = _unit((await embed_texts([query], cost_tracker))[0])
    except Exception as exc:  # any provider/import/shape failure → BM25-only retrieval
        kind = type(exc).__name__
        level = logging.DEBUG if kind in _warned else logging.WARNING
        _warned.add(kind)  # e.g. anthropic_only profile: warn once, not once per claim
        logger.log(level, "Embedding retrieval unavailable (%s: %s); using BM25 only",
                   kind, str(exc)[:200])
        return None
    if doc_vectors and len(doc_vectors[0]) != len(query_vector):
        # The embedding role fell back to another model mid-run; vectors are not comparable.
        _vector_cache.pop(doc.fingerprint, None)
        logger.warning("Embedding dimension changed; using BM25 only for this claim")
        return None
    scored = [
        (window.idx, sum(map(operator.mul, query_vector, vec)))
        for window, vec in zip(windows, doc_vectors, strict=True)
    ]
    scored.sort(key=lambda kv: (-kv[1], kv[0]))
    return scored[:top_n]


def clear_embedding_cache() -> None:
    """Drop cached window vectors (tests)."""
    _vector_cache.clear()
    _inflight.clear()
