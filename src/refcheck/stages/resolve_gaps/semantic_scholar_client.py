"""Async client for Semantic Scholar API."""

import logging
import os
from typing import Literal

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

S2_BASE = "https://api.semanticscholar.org/graph/v1"
_TIMEOUT = 15.0


class S2Result:
    """Container for Semantic Scholar lookup result."""

    def __init__(
        self,
        *,
        found: bool,
        title: str = "",
        authors: list[str] | None = None,
        year: int | None = None,
        doi: str = "",
        abstract: str = "",
        oa_url: str = "",
        citation_count: int = 0,
        status: Literal["found", "not_found", "api_error"] = "not_found",
    ) -> None:
        self.found = found
        self.title = title
        self.authors = authors or []
        self.year = year
        self.doi = doi
        self.abstract = abstract
        self.oa_url = oa_url
        self.citation_count = citation_count
        self.status = status


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5))
async def search_by_title(
    title: str,
    client: httpx.AsyncClient | None = None,
) -> S2Result:
    """Search Semantic Scholar by title."""
    api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")
    headers: dict[str, str] = {}
    if api_key:
        headers["x-api-key"] = api_key

    params = {
        "query": title,
        "limit": "1",
        "fields": "title,year,authors,externalIds,abstract,openAccessPdf,citationCount",
    }
    should_close = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=_TIMEOUT)

    try:
        resp = await client.get(
            f"{S2_BASE}/paper/search", params=params, headers=headers
        )
        resp.raise_for_status()
        data = resp.json()
        papers = data.get("data", [])
        if not papers:
            return S2Result(found=False, status="not_found")
        return _parse_s2_paper(papers[0])
    except httpx.TimeoutException:
        logger.warning("Semantic Scholar timeout")
        return S2Result(found=False, status="api_error")
    except httpx.HTTPStatusError:
        return S2Result(found=False, status="api_error")
    finally:
        if should_close:
            await client.aclose()


def _parse_s2_paper(paper: dict[str, object]) -> S2Result:
    """Parse a Semantic Scholar paper object."""
    title = str(paper.get("title", ""))
    year_val = paper.get("year")
    year = int(str(year_val)) if year_val is not None else None

    ext_ids = paper.get("externalIds", {})
    doi = str(ext_ids.get("DOI", "")) if isinstance(ext_ids, dict) else ""

    oa_pdf = paper.get("openAccessPdf")
    oa_url = ""
    if isinstance(oa_pdf, dict):
        oa_url = str(oa_pdf.get("url", ""))

    authors_raw = paper.get("authors", [])
    authors: list[str] = []
    if isinstance(authors_raw, list):
        for a in authors_raw:
            if isinstance(a, dict):
                name = a.get("name", "")
                if name:
                    authors.append(str(name))

    citation_val = paper.get("citationCount", 0)
    citation_count = int(str(citation_val)) if citation_val is not None else 0

    return S2Result(
        found=bool(title),
        title=title,
        authors=authors,
        year=year,
        doi=doi,
        oa_url=oa_url,
        citation_count=citation_count,
        status="found" if title else "not_found",
    )
