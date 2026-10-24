"""Hybrid passage retrieval for claim verification.

Candidates = BM25 top-n ∪ embedding top-n over the source's windows, fused by
reciprocal-rank fusion (k=60). The pack holds the abstract unit "A" first,
then windows best-first (adjacent windows merged) up to a token budget:
3,000 tokens for the standard pack, 8,000 for the expanded pack. Embedding
failures degrade to BM25 only; abstract-only sources yield a pack with "A".
"""

import re
import threading
import unicodedata
from collections import OrderedDict
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from refcheck.stages.verify_claims.bm25 import BM25Index
from refcheck.stages.verify_claims.retrieval_embed import embedding_ranking
from refcheck.stages.verify_claims.retrieval_models import (
    EvidencePack,
    Passage,
    passage_label,
    render_pack,
)
from refcheck.stages.verify_claims.retrieval_pack import assemble_pack
from refcheck.stages.verify_claims.source_models import SourceDocument

if TYPE_CHECKING:
    from refcheck.llm.cost_tracker import CostTracker

__all__ = [
    "EXPANDED_PACK_TOKENS", "STANDARD_PACK_TOKENS", "EvidencePack", "Passage", "Ranking",
    "bm25_pack", "clean_query", "expanded_pack", "fuse_rrf", "passage_label", "rank_units",
    "render_pack", "retrieve",
]

RETRIEVAL_VERSION = "v5.1-w3s2"
STANDARD_PACK_TOKENS = 3000
EXPANDED_PACK_TOKENS = 8000
EXPANDED_TOP_N = 60
RRF_K = 60
_BM25_CACHE_SIZE = 32
_bm25_cache: "OrderedDict[str, BM25Index]" = OrderedDict()
_bm25_lock = threading.Lock()

_CITATION_RES = [
    re.compile(r"<\|[a-z_]+\|>"),  # dataset markers such as <|multi_cit|>
    re.compile(r"\[\s*\d+(?:\s*[-–,;]\s*\d+)*\s*\]"),  # [12], [3-5, 9]
    re.compile(r"\(\s*\d+(?:\s*[-–,;]\s*\d+)*\s*\)"),  # (12), (3,4)
    re.compile(r"\([A-Z][^()]{0,80}?\b(?:19|20)\d{2}[a-z]?\)"),  # (Smith et al., 2010)
    re.compile(r"(?<!\w)#(?!\w)"),  # other-reference placeholders
    re.compile(r"(?<=[a-z]{4})\d{1,3}(?:[,–-]\d{1,3})*\b"),  # superscripts: "cyclical36"
    re.compile(r"(?<![\w.])–\d{1,3}\b"),  # dangling range end: "#–36"
]


class Ranking(BaseModel):
    """Window chunk indices best-first, with fused scores."""

    ranked: list[tuple[int, float]] = Field(default_factory=list)
    used_embeddings: bool = False
    n_candidates: int = 0  # size of the fused BM25 ∪ embedding candidate set


def clean_query(query: str) -> str:
    """Remove citation markers so reference numbers do not match source digits.

    The query is NFKC-normalised like the source text (sanitize_source_text), so
    BM25 and the embedding model compare the same spelling on both sides.
    """
    query = unicodedata.normalize("NFKC", query)
    for pattern in _CITATION_RES:
        query = pattern.sub(" ", query)
    return " ".join(query.split())


def fuse_rrf(rankings: list[list[int]], k: int = RRF_K) -> list[tuple[int, float]]:
    """Reciprocal-rank fusion: score = Σ 1/(k + rank), ranks starting at 1."""
    scores: dict[int, float] = {}
    first_seen: dict[int, tuple[int, int]] = {}
    for list_i, ranking in enumerate(rankings):
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
            first_seen.setdefault(item, (rank, list_i))
    return sorted(scores.items(), key=lambda kv: (-kv[1], first_seen[kv[0]], kv[0]))


def _bm25_index(doc: SourceDocument) -> BM25Index:
    # Locked: bm25_pack may run in worker threads (asyncio.to_thread callers).
    with _bm25_lock:
        index = _bm25_cache.get(doc.fingerprint)
        if index is not None:
            _bm25_cache.move_to_end(doc.fingerprint)
            return index
    index = BM25Index([w.text for w in doc.windows])
    with _bm25_lock:
        _bm25_cache[doc.fingerprint] = index
        while len(_bm25_cache) > _BM25_CACHE_SIZE:
            _bm25_cache.popitem(last=False)
    return index


def bm25_ranking(query: str, doc: SourceDocument) -> list[tuple[int, float]]:
    """Every window sharing a term with the query: (chunk idx, BM25 score), best first."""
    windows = doc.windows
    if not windows:
        return []
    return [(windows[i].idx, score) for i, score in _bm25_index(doc).rank_all(query)]


def _with_tail(fused: list[tuple[int, float]], bm25: list[tuple[int, float]],
               doc: SourceDocument) -> list[tuple[int, float]]:
    """Fused candidates, then remaining BM25 hits, then the rest in document order."""
    seen = {idx for idx, _ in fused}
    tail = [(idx, 0.0) for idx, _ in bm25 if idx not in seen]
    seen.update(idx for idx, _ in tail)
    tail.extend((w.idx, 0.0) for w in doc.windows if w.idx not in seen)
    return fused + tail


def _rank_bm25_only(query: str, doc: SourceDocument, top_n: int) -> Ranking:
    bm25 = bm25_ranking(query, doc)
    fused = fuse_rrf([[idx for idx, _ in bm25[:top_n]]])
    return Ranking(ranked=_with_tail(fused, bm25, doc), n_candidates=len(fused))


async def rank_units(
    query: str,
    doc: SourceDocument,
    top_n: int = 30,
    use_embeddings: bool = True,
    cost_tracker: "CostTracker | None" = None,
) -> Ranking:
    """Rank all windows: RRF(BM25 top-n, embedding top-n) first, then a BM25/doc-order tail."""
    query = clean_query(query)
    if not use_embeddings or not doc.windows:
        return _rank_bm25_only(query, doc, top_n)
    dense = await embedding_ranking(query, doc, top_n, cost_tracker)
    if dense is None:
        return _rank_bm25_only(query, doc, top_n)
    bm25 = bm25_ranking(query, doc)
    fused = fuse_rrf([[idx for idx, _ in bm25[:top_n]], [idx for idx, _ in dense[:top_n]]])
    return Ranking(ranked=_with_tail(fused, bm25, doc), used_embeddings=True,
                   n_candidates=len(fused))


def _version(used_embeddings: bool) -> str:
    return f"{RETRIEVAL_VERSION}:" + (f"bm25+emb-rrf{RRF_K}" if used_embeddings else "bm25")


async def retrieve(
    query: str,
    doc: SourceDocument,
    max_tokens: int = STANDARD_PACK_TOKENS,
    top_n: int = 30,
    use_embeddings: bool = True,
    cost_tracker: "CostTracker | None" = None,
) -> EvidencePack:
    """Standard evidence pack for a claim (≤3,000 tokens by default)."""
    if doc.coverage == "abstract_only":
        return assemble_pack(doc, [], max_tokens, _version(False), query=query)
    ranking = await rank_units(query, doc, top_n, use_embeddings, cost_tracker)
    return assemble_pack(doc, ranking.ranked, max_tokens, _version(ranking.used_embeddings),
                         used_embeddings=ranking.used_embeddings, query=query)


async def expanded_pack(
    query: str,
    doc: SourceDocument,
    max_tokens: int = EXPANDED_PACK_TOKENS,
    top_n: int = EXPANDED_TOP_N,
    use_embeddings: bool = True,
    cost_tracker: "CostTracker | None" = None,
) -> EvidencePack:
    """Expanded pack (≤8,000 tokens) for the judge / insufficient-evidence retry."""
    return await retrieve(query, doc, max_tokens, top_n, use_embeddings, cost_tracker)


def bm25_pack(
    query: str, doc: SourceDocument, max_tokens: int = STANDARD_PACK_TOKENS, top_n: int = 30,
) -> EvidencePack:
    """Synchronous BM25-only pack (no network), e.g. for compatibility callers."""
    if doc.coverage == "abstract_only":
        return assemble_pack(doc, [], max_tokens, _version(False), query=query)
    ranking = _rank_bm25_only(clean_query(query), doc, top_n)
    return assemble_pack(doc, ranking.ranked, max_tokens, _version(False), query=query)
