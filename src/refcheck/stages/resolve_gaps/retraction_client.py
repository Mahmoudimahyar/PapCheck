"""Check retraction status via CrossRef and PubMed."""

import logging
from typing import Literal

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class RetractionStatus(BaseModel):
    """Retraction check result for a single reference."""

    status: Literal[
        "ok", "retracted", "corrected", "expression_of_concern", "unknown"
    ] = "unknown"
    detail: str = ""
    source: str = ""
    retraction_doi: str | None = None
    retraction_date: str | None = None


_SEVERITY = {
    "retracted": 4,
    "expression_of_concern": 3,
    "corrected": 2,
    "ok": 1,
    "unknown": 0,
}

CROSSREF_BASE = "https://api.crossref.org"


async def check_retraction_status(
    doi: str | None,
    title: str | None,
    pmid: str | None,
    http_client: httpx.AsyncClient,
) -> RetractionStatus:
    """Check if a paper has been retracted, corrected, or flagged.

    Queries CrossRef (if DOI) and PubMed (if PMID). Returns most severe status.
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
        return RetractionStatus(status="ok", detail="No retraction info found")

    # Return the most severe status
    return max(results, key=lambda r: _SEVERITY.get(r.status, 0))


async def _check_crossref(
    doi: str, client: httpx.AsyncClient,
) -> RetractionStatus | None:
    """Check CrossRef for retraction/correction via update-to field."""
    try:
        resp = await client.get(f"{CROSSREF_BASE}/works/{doi}", timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
        msg = data.get("message", {})
        if not isinstance(msg, dict):
            return None
        return _parse_crossref_updates(msg, doi)
    except (httpx.TimeoutException, httpx.HTTPStatusError):
        logger.warning("CrossRef retraction check failed for DOI %s", doi)
        return None
    except Exception:
        logger.warning("CrossRef retraction check error for DOI %s", doi)
        return None


def _parse_crossref_updates(
    msg: dict[str, object], doi: str,
) -> RetractionStatus | None:
    """Parse CrossRef update-to field for retraction info."""
    updates = msg.get("update-to", [])
    if not isinstance(updates, list) or not updates:
        return RetractionStatus(status="ok", source="crossref")

    for update in updates:
        if not isinstance(update, dict):
            continue
        update_type = str(update.get("type", "")).lower()
        update_label = str(update.get("label", ""))
        update_doi = str(update.get("DOI", ""))
        date_str = _extract_crossref_date(update)

        if "retraction" in update_type:
            return RetractionStatus(
                status="retracted", detail=update_label,
                source="crossref", retraction_doi=update_doi,
                retraction_date=date_str,
            )
        if "correction" in update_type or "erratum" in update_type:
            return RetractionStatus(
                status="corrected", detail=update_label,
                source="crossref", retraction_doi=update_doi,
                retraction_date=date_str,
            )
        if "concern" in update_type:
            return RetractionStatus(
                status="expression_of_concern", detail=update_label,
                source="crossref", retraction_doi=update_doi,
                retraction_date=date_str,
            )

    return RetractionStatus(status="ok", source="crossref")


def _extract_crossref_date(update: dict[str, object]) -> str:
    """Extract date string from CrossRef update entry."""
    date_parts = update.get("updated", {})
    if isinstance(date_parts, dict):
        parts = date_parts.get("date-parts", [[]])
        if isinstance(parts, list) and parts and isinstance(parts[0], list):
            return "-".join(str(p) for p in parts[0])
    return ""


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
        return _parse_pubmed_retraction(resp.text)
    except (httpx.TimeoutException, httpx.HTTPStatusError):
        logger.warning("PubMed retraction check failed for PMID %s", pmid)
        return None
    except Exception:
        logger.warning("PubMed retraction check error for PMID %s", pmid)
        return None


def _parse_pubmed_retraction(xml_text: str) -> RetractionStatus | None:
    """Parse PubMed XML for retraction-related publication types."""
    text_lower = xml_text.lower()
    if "retracted publication" in text_lower:
        return RetractionStatus(
            status="retracted", detail="Retracted Publication",
            source="pubmed",
        )
    if "published erratum" in text_lower or "erratum" in text_lower:
        return RetractionStatus(
            status="corrected", detail="Published Erratum",
            source="pubmed",
        )
    if "expression of concern" in text_lower:
        return RetractionStatus(
            status="expression_of_concern",
            detail="Expression of Concern", source="pubmed",
        )
    return RetractionStatus(status="ok", source="pubmed")
