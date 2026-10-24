"""Library repository — CRUD operations for stored papers."""

import hashlib
import json
import logging
import shutil
from pathlib import Path

from rapidfuzz import fuzz
from sqlmodel import Session, select

from refcheck.library.engine import LIBRARY_PDF_DIR
from refcheck.library.models import LibraryPaper

logger = logging.getLogger(__name__)


def compute_pdf_hash(pdf_path: Path) -> str:
    """Compute SHA-256 hash of a PDF file."""
    sha256 = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def add_paper(
    db: Session,
    pdf_path: Path,
    doi: str | None,
    pmid: str | None,
    title: str,
    authors: list[str],
    year: int | None,
    journal: str | None,
    source: str,
    session_id: str | None = None,
    pdf_dir: Path | None = None,
) -> LibraryPaper:
    """Add a paper to the library. Deduplicates by PDF hash."""
    target_dir = pdf_dir or LIBRARY_PDF_DIR
    pdf_hash = compute_pdf_hash(pdf_path)

    existing = db.exec(
        select(LibraryPaper).where(LibraryPaper.pdf_hash == pdf_hash)
    ).first()
    if existing:
        return existing

    sanitized = "".join(
        c for c in title[:60] if c.isalnum() or c in " -_"
    ).strip()
    dest_name = f"{pdf_hash[:8]}_{sanitized}.pdf"
    dest_path = target_dir / dest_name
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pdf_path, dest_path)

    paper = LibraryPaper(
        doi=doi, pmid=pmid, title=title,
        authors_json=json.dumps(authors), year=year, journal=journal,
        pdf_path=str(dest_path), pdf_hash=pdf_hash,
        source=source, source_session_id=session_id,
    )
    db.add(paper)
    db.commit()
    db.refresh(paper)
    logger.info("Added paper to library: %s (hash=%s)", title[:50], pdf_hash[:8])
    return paper


def find_paper(
    db: Session,
    doi: str | None = None,
    pmid: str | None = None,
    title: str | None = None,
) -> LibraryPaper | None:
    """Find a paper by DOI, PMID, or fuzzy title match (>92)."""
    if doi:
        result = db.exec(
            select(LibraryPaper).where(LibraryPaper.doi == doi)
        ).first()
        if result:
            return result
    if pmid:
        result = db.exec(
            select(LibraryPaper).where(LibraryPaper.pmid == pmid)
        ).first()
        if result:
            return result
    if title:
        all_papers = db.exec(select(LibraryPaper)).all()
        for paper in all_papers:
            ratio = fuzz.token_sort_ratio(title.lower(), paper.title.lower())
            if ratio > 92:
                return paper
    return None


def search_papers(
    db: Session, query: str, limit: int = 20,
) -> list[LibraryPaper]:
    """Search library by title/author with fuzzy matching."""
    all_papers = db.exec(select(LibraryPaper)).all()
    scored: list[tuple[float, LibraryPaper]] = []
    for paper in all_papers:
        score = max(
            fuzz.partial_ratio(query.lower(), paper.title.lower()),
            fuzz.partial_ratio(query.lower(), paper.authors_json.lower()),
        )
        if score > 60:
            scored.append((score, paper))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [paper for _, paper in scored[:limit]]


class LibraryStats:
    """Library statistics result."""

    def __init__(
        self, total: int, with_pdf: int, by_source: dict[str, int],
    ) -> None:
        self.total = total
        self.with_pdf = with_pdf
        self.by_source = by_source


def get_stats(db: Session) -> LibraryStats:
    """Get library statistics."""
    all_papers = db.exec(select(LibraryPaper)).all()
    by_source: dict[str, int] = {}
    for paper in all_papers:
        by_source[paper.source] = by_source.get(paper.source, 0) + 1
    return LibraryStats(
        total=len(all_papers),
        with_pdf=sum(1 for p in all_papers if p.pdf_path),
        by_source=by_source,
    )
