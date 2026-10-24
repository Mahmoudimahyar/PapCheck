"""Cached DOI lookups: CrossRef works (abstract + retraction), S2 abstracts."""

import asyncio
import logging
import os
from urllib.parse import quote

import httpx
from pydantic import BaseModel, Field

from refcheck.stages.resolve_gaps.http_retry import send_with_backoff
from refcheck.stages.resolve_gaps.markup import strip_jats
from refcheck.stages.resolve_gaps.record_cache import load_record, store_record
from refcheck.stages.resolve_gaps.retraction_parsing import (
    RetractionStatus,
    parse_crossref_retraction,
)
from refcheck.utils.doi import normalize_doi

logger = logging.getLogger(__name__)

CROSSREF_WORKS = "https://api.crossref.org/works/"
S2_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"
_S2_BATCH_SIZE = 500
_CROSSREF_KIND = "crossref_record_v1"
_S2_KIND = "s2_abstract_v1"
_TIMEOUT = 20.0
_CONCURRENCY = 8


class CrossrefRecord(BaseModel):
    """The parts of a CrossRef work the pipeline needs."""

    doi: str
    title: str = ""
    abstract: str = ""
    retraction: RetractionStatus = Field(default_factory=RetractionStatus)


class S2Abstract(BaseModel):
    """Cached Semantic Scholar abstract for a DOI ("" = S2 has none)."""

    doi: str
    abstract: str = ""


def _unique_dois(dois: list[str]) -> list[str]:
    return [d for d in dict.fromkeys(normalize_doi(x) for x in dois if x) if d]


async def fetch_crossref_records(
    dois: list[str], client: httpx.AsyncClient,
) -> dict[str, CrossrefRecord]:
    """CrossRef records keyed by normalized DOI (misses/errors omitted)."""
    records: dict[str, CrossrefRecord] = {}
    missing: list[str] = []
    for doi in _unique_dois(dois):
        cached = load_record(_CROSSREF_KIND, doi, CrossrefRecord)
        if cached is not None:
            records[doi] = cached
        else:
            missing.append(doi)

    sem = asyncio.Semaphore(_CONCURRENCY)

    async def _one(doi: str) -> None:
        async with sem:
            record = await _fetch_crossref(doi, client)
        if record is not None:
            store_record(_CROSSREF_KIND, doi, record)
            records[doi] = record

    await asyncio.gather(*[_one(d) for d in missing])
    return records


async def _fetch_crossref(
    doi: str, client: httpx.AsyncClient,
) -> CrossrefRecord | None:
    """GET one CrossRef work; None if not found or the API failed."""
    headers: dict[str, str] = {}
    email = os.environ.get("UNPAYWALL_EMAIL", "")
    if email:
        headers["User-Agent"] = f"RefCheck/0.1 (mailto:{email})"
    try:
        url = f"{CROSSREF_WORKS}{quote(doi, safe='/')}"
        resp = await send_with_backoff(
            lambda: client.get(url, headers=headers, timeout=_TIMEOUT),
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        msg = resp.json().get("message", {})
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("CrossRef lookup failed for DOI %s: %s", doi, exc)
        return None
    if not isinstance(msg, dict):
        return None
    titles = msg.get("title") or []
    title = str(titles[0]) if isinstance(titles, list) and titles else ""
    return CrossrefRecord(
        doi=doi,
        title=title,
        abstract=strip_jats(str(msg.get("abstract") or "")),
        retraction=parse_crossref_retraction(msg, doi),
    )


async def fetch_s2_abstracts(
    dois: list[str], client: httpx.AsyncClient,
) -> dict[str, str]:
    """Semantic Scholar abstracts keyed by normalized DOI (batch endpoint)."""
    abstracts: dict[str, str] = {}
    missing: list[str] = []
    for doi in _unique_dois(dois):
        cached = load_record(_S2_KIND, doi, S2Abstract)
        if cached is not None:
            abstracts[doi] = cached.abstract
        else:
            missing.append(doi)

    for start in range(0, len(missing), _S2_BATCH_SIZE):
        batch = missing[start:start + _S2_BATCH_SIZE]
        papers = await _s2_batch(batch, client)
        if papers is None:
            continue
        for doi, paper in zip(batch, papers, strict=False):
            text = ""
            if isinstance(paper, dict):
                text = str(paper.get("abstract") or "").strip()
            store_record(_S2_KIND, doi, S2Abstract(doi=doi, abstract=text))
            abstracts[doi] = text
    return abstracts


async def _s2_batch(
    dois: list[str], client: httpx.AsyncClient,
) -> list[object] | None:
    """POST one S2 batch request; None on API failure (logged)."""
    headers: dict[str, str] = {}
    api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")
    if api_key:
        headers["x-api-key"] = api_key
    try:
        resp = await send_with_backoff(lambda: client.post(
            S2_BATCH_URL,
            params={"fields": "abstract,externalIds"},
            json={"ids": [f"DOI:{d}" for d in dois]},
            headers=headers,
            timeout=_TIMEOUT,
        ))
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Semantic Scholar batch failed (%d DOIs): %s", len(dois), exc)
        return None
    return data if isinstance(data, list) else None
