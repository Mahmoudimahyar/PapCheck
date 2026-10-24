"""Library management endpoints (V2)."""

import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlmodel import Session as DBSession

from refcheck.library.engine import get_library_session
from refcheck.library.models import LibraryPaper
from refcheck.library.repository import (
    add_paper,
    get_stats,
    search_papers,
)

router = APIRouter()
logger = logging.getLogger(__name__)


class LibraryStatsResponse(BaseModel):
    """Library statistics."""

    total: int = 0
    with_pdf: int = 0
    by_source: dict[str, int] = {}


class LibraryPaperResponse(BaseModel):
    """Single library paper response."""

    id: int
    doi: str | None = None
    pmid: str | None = None
    title: str = ""
    year: int | None = None
    journal: str | None = None
    source: str = ""
    added_at: str = ""


def _paper_to_response(p: LibraryPaper) -> LibraryPaperResponse:
    return LibraryPaperResponse(
        id=p.id or 0, doi=p.doi, pmid=p.pmid,
        title=p.title, year=p.year, journal=p.journal,
        source=p.source, added_at=p.added_at,
    )


@router.get("/api/library", response_model=list[LibraryPaperResponse])
async def list_library(
    db: DBSession = Depends(get_library_session),
) -> list[LibraryPaperResponse]:
    """List all papers in the library."""
    papers = search_papers(db, "", limit=100)
    return [_paper_to_response(p) for p in papers]


@router.get("/api/library/stats", response_model=LibraryStatsResponse)
async def library_stats(
    db: DBSession = Depends(get_library_session),
) -> LibraryStatsResponse:
    """Get library statistics."""
    stats = get_stats(db)
    return LibraryStatsResponse(
        total=stats.total,
        with_pdf=stats.with_pdf,
        by_source=stats.by_source,
    )


@router.get("/api/library/search", response_model=list[LibraryPaperResponse])
async def search_library(
    q: str = "",
    db: DBSession = Depends(get_library_session),
) -> list[LibraryPaperResponse]:
    """Search library papers by title/author."""
    if not q:
        return []
    papers = search_papers(db, q)
    return [_paper_to_response(p) for p in papers]


@router.post("/api/library/upload", response_model=LibraryPaperResponse)
async def upload_to_library(
    pdf: UploadFile,
    title: str = "Untitled",
    doi: str | None = None,
    db: DBSession = Depends(get_library_session),
) -> LibraryPaperResponse:
    """Upload a PDF directly to the library."""
    if not pdf.filename or not pdf.filename.endswith(".pdf"):
        raise HTTPException(400, "File must be a PDF")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        content = await pdf.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    paper = add_paper(
        db, tmp_path, doi=doi, pmid=None,
        title=title, authors=[], year=None,
        journal=None, source="user_upload",
    )
    return _paper_to_response(paper)


@router.delete("/api/library/{paper_id}")
async def delete_library_paper(
    paper_id: int,
    db: DBSession = Depends(get_library_session),
) -> dict[str, str]:
    """Remove a paper from the library."""
    paper = db.get(LibraryPaper, paper_id)
    if not paper:
        raise HTTPException(404, "Paper not found")
    db.delete(paper)
    db.commit()
    return {"status": "deleted"}
