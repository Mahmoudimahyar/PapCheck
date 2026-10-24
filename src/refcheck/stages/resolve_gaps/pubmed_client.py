"""Async client for PubMed/NCBI E-utilities API."""

import logging
import os
from typing import Literal

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from refcheck.stages.resolve_gaps.http_retry import send_with_backoff
from refcheck.stages.resolve_gaps.markup import (
    parse_pubmed_abstract,
    parse_pubmed_year,
    split_pubmed_articles,
    strip_markup,
)
from refcheck.stages.resolve_gaps.title_guard import pick_best_hit

logger = logging.getLogger(__name__)

PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
_TIMEOUT = 15.0
_TITLE_CANDIDATES = 5


class PubMedResult:
    """Container for PubMed lookup result."""

    def __init__(
        self,
        *,
        found: bool,
        pmid: str = "",
        title: str = "",
        authors: list[str] | None = None,
        year: int | None = None,
        doi: str = "",
        pmc_id: str = "",
        abstract: str = "",
        status: Literal["found", "not_found", "api_error"] = "not_found",
    ) -> None:
        self.found = found
        self.pmid = pmid
        self.title = title
        self.authors = authors or []
        self.year = year
        self.doi = doi
        self.pmc_id = pmc_id
        self.abstract = abstract
        self.status = status


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5))
async def search_by_pmid(
    pmid: str,
    client: httpx.AsyncClient | None = None,
) -> PubMedResult:
    """Look up a paper by PubMed ID."""
    api_key = os.environ.get("NCBI_API_KEY", "")
    params: dict[str, str] = {
        "db": "pubmed",
        "id": pmid,
        "retmode": "xml",
    }
    if api_key:
        params["api_key"] = api_key

    should_close = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=_TIMEOUT)

    try:
        http = client
        resp = await send_with_backoff(
            lambda: http.get(f"{PUBMED_BASE}efetch.fcgi", params=params),
        )
        resp.raise_for_status()
        return _parse_pubmed_xml(resp.text, pmid)
    except httpx.TimeoutException:
        logger.warning("PubMed timeout for PMID %s", pmid)
        return PubMedResult(found=False, status="api_error")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return PubMedResult(found=False, status="not_found")
        logger.error("PubMed HTTP error: %s", exc)
        return PubMedResult(found=False, status="api_error")
    finally:
        if should_close:
            await client.aclose()


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5))
async def search_by_title(
    title: str,
    client: httpx.AsyncClient | None = None,
) -> PubMedResult:
    """Search PubMed by title and return first result."""
    api_key = os.environ.get("NCBI_API_KEY", "")
    params: dict[str, str] = {
        "db": "pubmed",
        "term": f"{title}[Title]",
        # Several candidates: the top one is often an addendum/erratum.
        "retmax": str(_TITLE_CANDIDATES),
        "retmode": "json",
    }
    if api_key:
        params["api_key"] = api_key

    should_close = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=_TIMEOUT)

    try:
        http = client
        resp = await send_with_backoff(
            lambda: http.get(f"{PUBMED_BASE}esearch.fcgi", params=params),
        )
        resp.raise_for_status()
        data = resp.json()
        id_list = data.get("esearchresult", {}).get("idlist", [])
        if not id_list:
            return PubMedResult(found=False, status="not_found")
        if len(id_list) == 1:
            return await search_by_pmid(id_list[0], client)
        return await _best_candidate(title, id_list, http)
    except httpx.TimeoutException:
        logger.warning("PubMed title search timeout")
        return PubMedResult(found=False, status="api_error")
    except httpx.HTTPStatusError:
        return PubMedResult(found=False, status="api_error")
    finally:
        if should_close:
            await client.aclose()


async def _best_candidate(
    title: str, pmids: list[str], client: httpx.AsyncClient,
) -> PubMedResult:
    """efetch all candidates in one request; keep the best title match."""
    params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"}
    api_key = os.environ.get("NCBI_API_KEY", "")
    if api_key:
        params["api_key"] = api_key
    resp = await send_with_backoff(
        lambda: client.get(f"{PUBMED_BASE}efetch.fcgi", params=params),
    )
    resp.raise_for_status()
    articles = split_pubmed_articles(resp.text)
    candidates = [
        _parse_pubmed_xml(articles[p], p) for p in pmids if p in articles
    ]
    best = pick_best_hit(title, [c for c in candidates if c.found], lambda c: c.title)
    return best or PubMedResult(found=False, status="not_found")


def _parse_pubmed_xml(xml_text: str, pmid: str) -> PubMedResult:
    """Parse PubMed eFetch XML response (minimal extraction)."""
    # Simplified XML parsing — extract key fields. Year comes from PubDate:
    # the first <Year> in the record is DateCompleted/DateRevised.
    title = strip_markup(_extract_xml_tag(xml_text, "ArticleTitle"))
    doi = _extract_xml_tag(xml_text, "ArticleId IdType=\"doi\"")
    pmc_id = _extract_xml_tag(xml_text, "ArticleId IdType=\"pmc\"")

    if not title:
        return PubMedResult(found=False, pmid=pmid, status="not_found")

    return PubMedResult(
        found=True,
        pmid=pmid,
        title=title,
        year=parse_pubmed_year(xml_text),
        doi=doi,
        pmc_id=pmc_id,
        abstract=parse_pubmed_abstract(xml_text),
        status="found",
    )


def _extract_xml_tag(xml: str, tag: str) -> str:
    """Simple XML tag extraction without full parser."""
    import re

    # Handle tags with attributes
    tag_name = tag.split()[0]
    pattern = rf"<{tag}[^>]*>(.*?)</{tag_name}>"
    match = re.search(pattern, xml, re.DOTALL)
    return match.group(1).strip() if match else ""
