"""Orchestrate reference resolution across academic APIs.

Open-access PDF downloads (PMC, Unpaywall) need the user's consent: they run only with
REFCHECK_OA_FETCH=on (library/oa_settings, default off) and never under pytest;
otherwise a found reference gets its journal_url (V5.8 G3).
"""

import asyncio
import logging
import os
from pathlib import Path

import httpx

from refcheck.library.oa_settings import oa_fetch_enabled, under_pytest
from refcheck.models.reference import Reference
from refcheck.stages.resolve_gaps.enrichment import enrich_references
from refcheck.stages.resolve_gaps.identity_check import apply_identity_checks
from refcheck.stages.resolve_gaps.lookups import (
    try_crossref,
    try_pubmed,
    try_semantic_scholar,
)
from refcheck.stages.resolve_gaps.oa_hints import FullTextGate, add_access_hints
from refcheck.stages.resolve_gaps.retriever import (
    download_pmc_pdf,
    download_unpaywall_pdf,
)

logger = logging.getLogger(__name__)

_DEFAULT_API_CONCURRENCY = 10


async def resolve_gaps(
    references: list[Reference],
    output_dir: Path | None = None,
    full_text_gate: FullTextGate | None = None,
) -> list[Reference]:
    """Resolve unmatched references via academic APIs.

    V3: Processes references concurrently with a semaphore to respect
    rate limits while maximizing throughput. V5: afterwards fills missing
    abstracts + retraction status (batched, cached) and checks that every
    attached PDF really is the cited paper (identity_status). Last, references
    without a usable full text (`full_text_gate`, default oa_hints.lacks_full_text)
    get a free-full-text hint from OpenAlex (metadata only).
    """
    if output_dir is None:
        output_dir = Path.home() / ".refcheck" / "cache" / "pdfs"

    # Per-call semaphore: a module-level one would bind to the first event loop.
    sem = asyncio.Semaphore(_api_concurrency())

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:

        async def _guarded_resolve(ref: Reference) -> Reference:
            if ref.pdf_path is not None:
                return ref
            async with sem:
                try:
                    return await _resolve_single(ref, output_dir, client)
                except Exception as exc:  # e.g. tenacity RetryError, bad JSON
                    # One failing lookup must not abort the whole stage.
                    logger.warning("Resolution failed for ref %d: %s", ref.id, exc)
                    return ref.model_copy(update={"source_status": "api_error"})

        results = list(await asyncio.gather(
            *[_guarded_resolve(ref) for ref in references],
        ))
        results = await _safe_enrich(results, client)
        results = await asyncio.to_thread(apply_identity_checks, results)
        return await add_access_hints(results, client, full_text_gate)


def _api_concurrency() -> int:
    """Max concurrent reference lookups (env REFCHECK_API_CONCURRENCY)."""
    try:
        return max(1, int(os.getenv("REFCHECK_API_CONCURRENCY", "")))
    except ValueError:
        return _DEFAULT_API_CONCURRENCY


async def _safe_enrich(
    refs: list[Reference], client: httpx.AsyncClient,
) -> list[Reference]:
    """Abstract/retraction enrichment must never fail the resolve stage."""
    try:
        return await enrich_references(refs, client)
    except Exception as exc:  # defensive: enrichment is best-effort
        logger.warning("Abstract/retraction enrichment failed: %s", exc)
        return refs


async def _resolve_single(
    ref: Reference,
    output_dir: Path,
    client: httpx.AsyncClient,
) -> Reference:
    """Resolve a single reference via cascading API lookups."""
    updates: dict[str, object] = {}

    # Try PubMed first (biomedical priority), then CrossRef, then S2.
    for lookup in (try_pubmed, try_crossref, try_semantic_scholar):
        if updates.get("source_status") == "found":
            break
        result = await lookup(ref, client)
        if result:
            updates.update(result)

    # Set not_found if no API returned results
    if "source_status" not in updates:
        updates["source_status"] = "not_found"

    # Try to download an OA PDF: only with the user's consent (module doc)
    if updates.get("source_status") == "found" and downloads_allowed():
        pdf_path = await _try_download(ref, updates, output_dir, client)
        if pdf_path:
            updates["pdf_path"] = pdf_path
            updates["pdf_source"] = "open_access"

    # Build journal_url for paywalled papers
    ref_doi = updates.get("doi") or ref.doi
    if ref_doi and "pdf_path" not in updates:
        updates["journal_url"] = f"https://doi.org/{ref_doi}"

    return ref.model_copy(update=updates)


def downloads_allowed() -> bool:
    """REFCHECK_OA_FETCH=on, and not a test run (module doc)."""
    return oa_fetch_enabled() and not under_pytest()


async def _try_download(
    ref: Reference,
    updates: dict[str, object],
    output_dir: Path,
    client: httpx.AsyncClient,
) -> Path | None:
    """Try to download OA PDF from PMC or Unpaywall."""
    # PMC download (biomedical priority)
    pmc_id = str(updates.get("pmc_id") or ref.pmc_id or "")
    if pmc_id:
        path = await download_pmc_pdf(pmc_id, output_dir, client)
        if path:
            return path

    # Unpaywall download
    doi = str(updates.get("doi") or ref.doi or "")
    if doi:
        path = await download_unpaywall_pdf(doi, output_dir, client)
        if path:
            return path

    return None
