"""Persistent reference library for sharing PDFs across sessions.

Stores PDFs in a shared directory indexed by DOI or title hash.
When a new session needs a PDF that was previously downloaded,
the library provides it without re-downloading.
"""

import hashlib
import logging
import shutil
from pathlib import Path

from refcheck.models.reference import Reference

logger = logging.getLogger(__name__)

_LIBRARY_DIR = Path.home() / ".refcheck" / "library"


def get_library_dir() -> Path:
    """Get the shared library directory, creating it if needed."""
    _LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    return _LIBRARY_DIR


def _pdf_key(ref: Reference) -> str:
    """Generate a stable key for a reference PDF."""
    if ref.doi:
        return f"doi_{hashlib.sha256(ref.doi.encode()).hexdigest()[:16]}"
    if ref.title:
        return f"title_{hashlib.sha256(ref.title.encode()).hexdigest()[:16]}"
    return f"ref_{ref.id}"


def lookup_in_library(ref: Reference) -> Path | None:
    """Check if a PDF exists in the shared library for this reference."""
    key = _pdf_key(ref)
    lib_dir = get_library_dir()
    pdf_path = lib_dir / f"{key}.pdf"
    if pdf_path.exists():
        logger.info("Library HIT: %s -> %s", ref.title or ref.doi, pdf_path)
        return pdf_path
    return None


def add_to_library(ref: Reference, source_pdf: Path) -> Path:
    """Copy a PDF into the shared library. Returns the library path."""
    key = _pdf_key(ref)
    lib_dir = get_library_dir()
    dest = lib_dir / f"{key}.pdf"

    if not dest.exists():
        shutil.copy2(source_pdf, dest)
        logger.info("Library ADD: %s -> %s", source_pdf.name, dest)

    return dest


def enrich_from_library(references: list[Reference]) -> list[Reference]:
    """Check the library for PDFs that match unresolved references.

    Returns a new list with pdf_path and pdf_source set for matches.
    """
    updated: list[Reference] = []
    hits = 0
    for ref in references:
        if ref.pdf_path is not None:
            updated.append(ref)
            continue
        lib_path = lookup_in_library(ref)
        if lib_path:
            updated.append(ref.model_copy(update={
                "pdf_path": str(lib_path),
                "pdf_source": "library",
            }))
            hits += 1
        else:
            updated.append(ref)

    if hits:
        logger.info("Library enriched %d/%d references", hits, len(references))
    return updated


def populate_library(references: list[Reference]) -> int:
    """Add resolved PDFs to the library for future sessions.

    Returns the number of PDFs added.
    """
    added = 0
    for ref in references:
        if ref.pdf_path and Path(ref.pdf_path).exists():
            existing = lookup_in_library(ref)
            if existing is None:
                add_to_library(ref, Path(ref.pdf_path))
                added += 1
    if added:
        logger.info("Library populated with %d new PDFs", added)
    return added


def get_library_stats() -> dict[str, int | float]:
    """Return library statistics."""
    lib_dir = get_library_dir()
    pdfs = list(lib_dir.glob("*.pdf"))
    total_bytes = sum(p.stat().st_size for p in pdfs)
    return {
        "pdf_count": len(pdfs),
        "total_size_mb": round(total_bytes / (1024 * 1024), 1),
    }
