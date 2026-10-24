"""Check retraction status via CrossRef and PubMed (one reference)."""

import logging

import httpx

from refcheck.stages.resolve_gaps.retraction_parsing import (
    RetractionStatus,
    most_severe,
    parse_crossref_retraction,
    parse_pubmed_retraction,
)

logger = logging.getLogger(__name__)

__all__ = [
    "RetractionStatus",
    "check_retraction_status",
    "most_severe",
    "parse_crossref_retraction",
    "parse_pubmed_retraction",
]

CROSSREF_BASE = "https://api.crossref.org"


async def check_retraction_status(
    doi: str | None,
    title: str | None,
    pmid: str | None,
    http_client: httpx.AsyncClient,
) -> RetractionStatus:
    """Check if a paper has been retracted, corrected, or flagged.

    Queries CrossRef (if DOI) and PubMed (if PMID). Returns most severe status.
    The resolve stage uses the batched/cached path in `enrichment` instead.
    """
    if not doi and not pmid:
        return RetractionStatus(status="unknown", detail="No DOI or PMID available")

    results: list[RetractionStatus] = []

    if doi:
        cr = await _check_crossref(doi, http_client)
        if cr:
            results.append(cr)

    if pmid:
        pm = await _check_pubmed(pmid, http_client)
        if pm:
            results.append(pm)

    if not results:
        # Every lookup failed: "couldn't check" is not "checked and clean".
        return RetractionStatus(
            status="unknown", detail="Retraction check failed (API unreachable)",
        )
    return most_severe(results)


async def _check_crossref(
    doi: str, client: httpx.AsyncClient,
) -> RetractionStatus | None:
    """Check CrossRef for retraction/correction via updated-by/update-to."""
    try:
        resp = await client.get(f"{CROSSREF_BASE}/works/{doi}", timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
        msg = data.get("message", {})
        if not isinstance(msg, dict):
            return None
        return parse_crossref_retraction(msg, doi)
    except (httpx.TimeoutException, httpx.HTTPStatusError):
        logger.warning("CrossRef retraction check failed for DOI %s", doi)
        return None
    except Exception:
        logger.warning("CrossRef retraction check error for DOI %s", doi)
        return None


async def _check_pubmed(
    pmid: str, client: httpx.AsyncClient,
) -> RetractionStatus | None:
    """Check PubMed for retraction publication type."""
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    try:
        resp = await client.get(
            f"{base}/efetch.fcgi",
            params={"db": "pubmed", "id": pmid, "retmode": "xml"},
            timeout=10.0,
        )
        resp.raise_for_status()
        return parse_pubmed_retraction(resp.text)
    except (httpx.TimeoutException, httpx.HTTPStatusError):
        logger.warning("PubMed retraction check failed for PMID %s", pmid)
        return None
    except Exception:
        logger.warning("PubMed retraction check error for PMID %s", pmid)
        return None
