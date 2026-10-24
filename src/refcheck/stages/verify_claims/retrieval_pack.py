"""Assemble an evidence pack from ranked retrieval units under a token budget.

The abstract unit goes first (≤400 tokens for full-text sources), then windows
in rank order. Windows of the same prose run that overlap or touch are merged
into one passage, so the 1-sentence overlap of stride-2 windows is paid once.
"""

import re

from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from refcheck.stages.verify_claims.retrieval_models import EvidencePack, Passage
from refcheck.stages.verify_claims.source_models import (
    Chunk,
    ChunkKind,
    SourceDocument,
    estimate_tokens,
)
from refcheck.stages.verify_claims.source_windows import split_sentences

ABSTRACT_MAX_TOKENS = 400
_MIN_USEFUL_TOKENS = 25
_ABSTRACT_DUP_SIMILARITY = 90


class _Group(BaseModel):
    run: int
    start: int
    end: int
    best_rank: int
    score: float
    unit_idx: int
    unit_idxs: list[int] = Field(default_factory=list)
    section: str
    kind: ChunkKind
    page: int | None
    text: str


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Whole sentences up to the budget; hard word cut (with "…") if one is too long."""
    if estimate_tokens(text) <= max_tokens:
        return text
    kept: list[str] = []
    for _, sentence in split_sentences(text):
        if estimate_tokens(" ".join([*kept, sentence])) > max_tokens:
            break
        kept.append(sentence)
    if kept:
        return " ".join(kept)
    cut = text[: max_tokens * 4].rsplit(" ", 1)[0]
    return f"{cut}…"


def assemble_pack(
    doc: SourceDocument,
    ranked: list[tuple[int, float]],
    max_tokens: int,
    retrieval_version: str,
    used_embeddings: bool = False,
    query: str = "",
) -> EvidencePack:
    """Pack = abstract unit, then ranked windows (merged when adjacent) within max_tokens."""
    passages: list[Passage] = []
    budget = max_tokens
    abstract_norm = ""
    abstract = doc.abstract_chunk
    if abstract is not None:
        full = doc.coverage == "full_text"
        cap = min(ABSTRACT_MAX_TOKENS, max_tokens) if full else max_tokens
        text = truncate_to_tokens(abstract.text, cap)
        passages.append(Passage(
            id="A", unit_idx=abstract.idx, unit_idxs=[abstract.idx], section="Abstract",
            page=abstract.page, kind="abstract", text=text, n_tokens=estimate_tokens(text),
        ))
        budget -= estimate_tokens(text)
        abstract_norm = _norm(text)
    if doc.coverage == "full_text":
        groups: list[_Group] = []
        for rank, (chunk_idx, score) in enumerate(ranked):
            if budget < _MIN_USEFUL_TOKENS:
                break
            chunk = doc.chunks[chunk_idx]
            if chunk.kind == "abstract" or _repeats_abstract(chunk, abstract_norm):
                continue
            budget -= _add(groups, chunk, rank, score, doc.sentences, budget)
        groups.sort(key=lambda g: g.best_rank)
        passages.extend(
            Passage(
                id=f"P{i}", unit_idx=g.unit_idx, unit_idxs=sorted(g.unit_idxs),
                section=g.section, page=g.page, kind=g.kind, text=g.text, score=g.score,
                n_tokens=estimate_tokens(g.text),
            )
            for i, g in enumerate(groups, start=1)
        )
    return EvidencePack(
        passages=passages, coverage=doc.coverage,
        total_tokens=sum(p.n_tokens for p in passages), retrieval_version=retrieval_version,
        used_embeddings=used_embeddings, max_tokens=max_tokens, query=query,
    )


def _add(
    groups: list[_Group], chunk: Chunk, rank: int, score: float,
    sentences: list[str], budget: int,
) -> int:
    """Add a window (merging with overlapping/adjacent groups); returns tokens spent."""
    touching = [
        g for g in groups
        if g.run == chunk.run and chunk.sent_start <= g.end and chunk.sent_end >= g.start
    ]
    if not touching:
        if chunk.n_tokens > budget:
            return 0
        groups.append(_Group(
            run=chunk.run, start=chunk.sent_start, end=chunk.sent_end, best_rank=rank,
            score=score, unit_idx=chunk.idx, unit_idxs=[chunk.idx], section=chunk.heading,
            kind=chunk.kind, page=chunk.page, text=chunk.text,
        ))
        return chunk.n_tokens
    start = min(chunk.sent_start, *(g.start for g in touching))
    end = max(chunk.sent_end, *(g.end for g in touching))
    text = " ".join(sentences[start:end])
    cost = estimate_tokens(text) - sum(estimate_tokens(g.text) for g in touching)
    if cost > budget:
        return 0
    best = min(touching, key=lambda g: g.best_rank)
    first = min(touching, key=lambda g: g.start)
    merged = _Group(
        run=chunk.run, start=start, end=end, best_rank=best.best_rank,
        score=max(best.score, score), unit_idx=best.unit_idx,
        unit_idxs=[i for g in touching for i in g.unit_idxs] + [chunk.idx],
        section=best.section, kind=best.kind,
        page=chunk.page if chunk.sent_start < first.start else first.page, text=text,
    )
    for g in touching:
        groups.remove(g)
    groups.append(merged)
    return max(cost, 0)


def _norm(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.lower()))


def _repeats_abstract(chunk: Chunk, abstract_norm: str) -> bool:
    """Windows that only repeat the (included) abstract text waste budget."""
    if not abstract_norm or chunk.heading not in ("Abstract", "other"):
        return False
    norm = _norm(chunk.text)
    if not norm or len(norm) > len(abstract_norm):
        return False
    if norm in abstract_norm:
        return True
    return fuzz.partial_ratio(norm, abstract_norm) >= _ABSTRACT_DUP_SIMILARITY
