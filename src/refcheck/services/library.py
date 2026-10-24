"""Shared PDF library: reuse PDFs of earlier runs, never a wrong one (V3; V5.8 G3).

Stage 4 calls `enrich_from_library` before the API lookups. A reference with no PDF,
or whose PDF is a supplement, a scan, unreadable or another paper (match_pdfs
`pdf_rejection` with the resolve stage's identity check), is looked up in the local
library (library/store.py): its DOI / title key and library.db, then a title + first
author + year scan of every library PDF, with the upload re-match evidence rules
(match_pdfs/library_match.py). A hit replaces the unusable PDF (pdf_source "library";
the uploaded file stays on disk). With REFCHECK_OA_FETCH=on (default off) a reference
still without one gets an open-access download (library/oa_fetch.py), kept only when
it passes the same checks, then stored in the library (pdf_source "open_access").
`populate_library` adds a run's usable PDFs afterwards: never a mismatch, supplement or
scan; a stored copy that is not this reference's paper is replaced by a verified one.
"""

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Literal

import httpx

from refcheck.library.oa_fetch import fetch_open_access
from refcheck.library.oa_settings import load_oa_settings
from refcheck.library.store import (
    db_paths,
    keyed_paths,
    library_db_path,
    library_pdfs,
    pdf_key,
    shared_library_dir,
)
from refcheck.models.reference import Reference
from refcheck.stages.match_pdfs.library_match import LibraryMatch, match_in_library
from refcheck.stages.match_pdfs.rematch import pdf_rejection
from refcheck.stages.match_pdfs.rematch_models import PdfReader, RejectReason
from refcheck.stages.resolve_gaps.pdf_identity import pdf_identity_status

logger = logging.getLogger(__name__)

_STAGING = ".staging"


def get_library_dir() -> Path:
    """The shared library directory, created if needed (write paths only)."""
    lib_dir = shared_library_dir()
    lib_dir.mkdir(parents=True, exist_ok=True)
    return lib_dir


def lookup_in_library(ref: Reference) -> Path | None:
    """The file stored under this reference's key (unchecked; None when there is none)."""
    paths = keyed_paths(ref, shared_library_dir())
    return paths[0] if paths else None


def add_to_library(ref: Reference, source_pdf: Path, replace: bool = False) -> Path:
    """Copy a PDF into the library under the reference's key; returns the library path."""
    dest = get_library_dir() / f"{pdf_key(ref)}.pdf"
    if dest.exists() and (not replace or dest.resolve() == source_pdf.resolve()):
        return dest
    shutil.copy2(source_pdf, dest)
    logger.info("Library %s: %s -> %s", "REPLACE" if replace else "ADD", source_pdf.name, dest)
    return dest


def reference_problem(ref: Reference, reader: PdfReader) -> RejectReason | None:
    """Why the reference has no usable PDF (None: its PDF can stand for it)."""
    if ref.pdf_path is None or not Path(ref.pdf_path).is_file():
        return "no_pdf"
    return pdf_rejection(ref, Path(ref.pdf_path), reader, pdf_identity_status)


def find_library_pdf(
    ref: Reference, references: list[Reference], reason: RejectReason, reader: PdfReader,
    lib_dir: Path, db_path: Path, pool: list[Path],
) -> LibraryMatch | None:
    """The library PDF that stands for `ref` (read-only; module doc)."""
    keyed = list(dict.fromkeys([*keyed_paths(ref, lib_dir), *db_paths(ref, db_path)]))
    return match_in_library(ref, keyed, pool, references, reader, pdf_identity_status, reason)


def enrich_from_library(
    references: list[Reference], oa_client: httpx.Client | None = None,
) -> list[Reference]:
    """Give references without a usable PDF one from the library (module doc)."""
    reader = PdfReader()
    needs = {r.id: reason for r in references if (reason := reference_problem(r, reader))}
    if not needs:
        return list(references)
    lib_dir, db_path = shared_library_dir(), library_db_path()
    pool = library_pdfs(lib_dir, db_path)
    updated: dict[int, Reference] = {}
    for ref in references:
        if ref.id in needs and pool:
            match = find_library_pdf(ref, references, needs[ref.id], reader, lib_dir, db_path,
                                     pool)
            if match is not None:
                updated[ref.id] = _linked(ref, Path(match.pdf_path), "library", needs[ref.id])
    missing = [r for r in references if r.id in needs and r.id not in updated]
    updated.update(_fetch_missing(missing, references, reader, oa_client, needs))
    if updated:
        logger.info("Library: %d of %d references without a usable PDF got one",
                    len(updated), len(needs))
    return [updated.get(r.id, r) for r in references]


async def enrich_from_library_async(references: list[Reference]) -> list[Reference]:
    """`enrich_from_library` off the event loop (PDF reads; an opted-in download)."""
    return await asyncio.to_thread(enrich_from_library, references)


def _fetch_missing(
    refs: list[Reference], references: list[Reference], reader: PdfReader,
    client: httpx.Client | None, needs: dict[int, RejectReason],
) -> dict[int, Reference]:
    """Opt-in open-access copies, identity-checked like an upload, stored in the library."""
    settings = load_oa_settings()
    if not settings.enabled or not refs:
        return {}
    staging = get_library_dir() / _STAGING
    found: dict[int, Reference] = {}
    for ref in refs[:settings.max_fetches]:
        def accept(path: Path, wanted: Reference = ref) -> bool:
            return match_in_library(wanted, [path], [], references, reader,
                                    pdf_identity_status, "no_pdf") is not None
        fetched = fetch_open_access(ref, staging, accept, settings, client)
        if fetched is None:
            continue
        stored = add_to_library(ref, fetched.path, replace=True)
        fetched.path.unlink(missing_ok=True)
        logger.info("OA fetch: ref %d <- %s (%s)", ref.id, fetched.source, fetched.url)
        found[ref.id] = _linked(ref, stored, "open_access", needs.get(ref.id, "no_pdf"))
    return found


def _linked(ref: Reference, path: Path, source: Literal["library", "open_access"],
            reason: RejectReason) -> Reference:
    """The reference with a new PDF (identity is checked again at the end of stage 4);
    an unusable upload's rejection is kept (``replaced_upload_reason``: a source issue)."""
    replaced = reason if reason != "no_pdf" and ref.pdf_path is not None else None
    return ref.model_copy(update={"pdf_path": path, "pdf_source": source,
                                  "source_status": "found", "identity_status": "unverified",
                                  "replaced_upload_reason": replaced})


def populate_library(references: list[Reference]) -> int:
    """Add a run's usable PDFs to the library for later runs; returns how many were stored."""
    reader = PdfReader()
    lib_dir = shared_library_dir()
    added = 0
    for ref in references:
        if ref.pdf_path is None or ref.identity_status == "mismatch" or not (ref.doi or ref.title):
            continue  # a "ref_<id>" key is per session: it would collide and is never looked up
        path = Path(ref.pdf_path)
        if not path.is_file() or path.parent.resolve() == lib_dir.resolve():
            continue  # gone, or already the library's own copy
        profile = reader.profile(path)
        if profile is None or not profile.usable or reader.supplement(path):
            continue
        existing = lookup_in_library(ref)
        if existing is None:
            add_to_library(ref, path)
        elif _replaces(ref, path, existing, reader):
            add_to_library(ref, path, replace=True)
        else:
            continue
        added += 1
    if added:
        logger.info("Library populated with %d PDFs", added)
    return added


def _replaces(ref: Reference, path: Path, stored: Path, reader: PdfReader) -> bool:
    """A verified PDF replaces a stored copy that cannot stand for the reference."""
    if ref.identity_status != "verified" or stored.resolve() == path.resolve():
        return False
    return pdf_rejection(ref, stored, reader, pdf_identity_status) is not None


def get_library_stats() -> dict[str, int | float]:
    """Return library statistics."""
    lib_dir = shared_library_dir()
    pdfs = list(lib_dir.glob("*.pdf")) if lib_dir.is_dir() else []
    total_bytes = sum(p.stat().st_size for p in pdfs)
    return {
        "pdf_count": len(pdfs),
        "total_size_mb": round(total_bytes / (1024 * 1024), 1),
    }
