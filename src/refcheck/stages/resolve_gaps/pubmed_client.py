"""Async client for PubMed/NCBI E-utilities API."""

import logging
import os
from typing import Literal

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
_TIMEOUT = 15.0


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
        resp = await client.get(f"{PUBMED_BASE}efetch.fcgi", params=params)
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
        "retmax": "1",
        "retmode": "json",
    }
    if api_key:
        params["api_key"] = api_key

    should_close = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=_TIMEOUT)

    try:
        resp = await client.get(f"{PUBMED_BASE}esearch.fcgi", params=params)
        resp.raise_for_status()
        data = resp.json()
        id_list = data.get("esearchresult", {}).get("idlist", [])
        if not id_list:
            return PubMedResult(found=False, status="not_found")
        return await search_by_pmid(id_list[0], client)
    except httpx.TimeoutException:
        logger.warning("PubMed title search timeout")
        return PubMedResult(found=False, status="api_error")
    except httpx.HTTPStatusError:
        return PubMedResult(found=False, status="api_error")
    finally:
        if should_close:
            await client.aclose()


def _parse_pubmed_xml(xml_text: str, pmid: str) -> PubMedResult:
    """Parse PubMed eFetch XML response (minimal extraction)."""
    # Simplified XML parsing — extract key fields
    title = _extract_xml_tag(xml_text, "ArticleTitle")
    year_str = _extract_xml_tag(xml_text, "Year")
    doi = _extract_xml_tag(xml_text, "ArticleId IdType=\"doi\"")
    pmc_id = _extract_xml_tag(xml_text, "ArticleId IdType=\"pmc\"")

    if not title:
        return PubMedResult(found=False, pmid=pmid, status="not_found")

    year = int(year_str) if year_str and year_str.isdigit() else None
    return PubMedResult(
        found=True,
        pmid=pmid,
        title=title,
        year=year,
        doi=doi,
        pmc_id=pmc_id,
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
