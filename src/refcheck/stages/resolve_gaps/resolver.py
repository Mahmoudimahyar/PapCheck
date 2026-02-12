"""Orchestrate reference resolution across academic APIs."""

import logging
from pathlib import Path

import httpx

from refcheck.models.reference import Reference
from refcheck.stages.resolve_gaps.crossref_client import (
    search_by_doi as crossref_by_doi,
)
from refcheck.stages.resolve_gaps.crossref_client import (
    search_by_title as crossref_by_title,
)
from refcheck.stages.resolve_gaps.pubmed_client import (
    search_by_pmid as pubmed_by_pmid,
)
from refcheck.stages.resolve_gaps.pubmed_client import (
    search_by_title as pubmed_by_title,
)
from refcheck.stages.resolve_gaps.retriever import (
    download_pmc_pdf,
    download_unpaywall_pdf,
)
from refcheck.stages.resolve_gaps.semantic_scholar_client import (
    search_by_title as s2_by_title,
)

logger = logging.getLogger(__name__)


async def resolve_gaps(
    references: list[Reference],
    output_dir: Path | None = None,
) -> list[Reference]:
    """Resolve unmatched references via academic APIs.

    For each reference without a PDF, queries PubMed, CrossRef,
    Semantic Scholar and attempts open-access download.
    """
    if output_dir is None:
        output_dir = Path.home() / ".refcheck" / "cache" / "pdfs"

    updated: list[Reference] = []
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        for ref in references:
            if ref.pdf_path is not None:
                updated.append(ref)
                continue
            resolved = await _resolve_single(ref, output_dir, client)
            updated.append(resolved)

    return updated


async def _resolve_single(
    ref: Reference,
    output_dir: Path,
    client: httpx.AsyncClient,
) -> Reference:
    """Resolve a single reference via cascading API lookups."""
    updates: dict[str, object] = {}

    # Try PubMed first (biomedical priority)
    pm_result = await _try_pubmed(ref, client)
    if pm_result:
        updates.update(pm_result)

    # Try CrossRef
    if updates.get("source_status") != "found":
        cr_result = await _try_crossref(ref, client)
        if cr_result:
            updates.update(cr_result)

    # Try Semantic Scholar
    if updates.get("source_status") != "found":
        s2_result = await _try_semantic_scholar(ref, client)
        if s2_result:
            updates.update(s2_result)

    # Set not_found if no API returned results
    if "source_status" not in updates:
        updates["source_status"] = "not_found"

    # Try to download OA PDF
    if updates.get("source_status") == "found":
        pdf_path = await _try_download(ref, updates, output_dir, client)
        if pdf_path:
            updates["pdf_path"] = pdf_path
            updates["pdf_source"] = "open_access"

    # Build journal_url for paywalled papers
    ref_doi = updates.get("doi") or ref.doi
    if ref_doi and "pdf_path" not in updates:
        updates["journal_url"] = f"https://doi.org/{ref_doi}"

    return ref.model_copy(update=updates)


async def _try_pubmed(
    ref: Reference,
    client: httpx.AsyncClient,
) -> dict[str, object] | None:
    """Try PubMed lookup by PMID or title."""
    if ref.pmid:
        result = await pubmed_by_pmid(ref.pmid, client)
    else:
        result = await pubmed_by_title(ref.title, client)

    if result.found:
        return {
            "source_status": "found",
            "pmid": result.pmid or ref.pmid,
        }
    if result.status == "api_error":
        return {"source_status": "api_error"}
    return None


async def _try_crossref(
    ref: Reference,
    client: httpx.AsyncClient,
) -> dict[str, object] | None:
    """Try CrossRef lookup by DOI or title."""
    if ref.doi:
        result = await crossref_by_doi(ref.doi, client)
    else:
        result = await crossref_by_title(ref.title, ref.authors, client)

    if result.found:
        return {
            "source_status": "found",
            "doi": result.doi or ref.doi,
            "journal_url": result.url,
        }
    if result.status == "api_error":
        return {"source_status": "api_error"}
    return None


async def _try_semantic_scholar(
    ref: Reference,
    client: httpx.AsyncClient,
) -> dict[str, object] | None:
    """Try Semantic Scholar title search."""
    if not ref.title:
        return None
    result = await s2_by_title(ref.title, client)
    if result.found:
        return {"source_status": "found", "doi": result.doi or ref.doi}
    if result.status == "api_error":
        return {"source_status": "api_error"}
    return None


async def _try_download(
    ref: Reference,
    updates: dict[str, object],
    output_dir: Path,
    client: httpx.AsyncClient,
) -> Path | None:
    """Try to download OA PDF from PMC or Unpaywall."""
    # PMC download (biomedical priority)
    pmid = str(updates.get("pmid", ref.pmid or ""))
    if pmid:
        path = await download_pmc_pdf(f"PMC{pmid}", output_dir, client)
        if path:
            return path

    # Unpaywall download
    doi = str(updates.get("doi", ref.doi or ""))
    if doi:
        path = await download_unpaywall_pdf(doi, output_dir, client)
        if path:
            return path

    return None
