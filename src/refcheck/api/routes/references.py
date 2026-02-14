"""Reference listing and management endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlmodel import Session as DBSession

from refcheck.db.converters import db_to_reference
from refcheck.db.deps import get_db
from refcheck.db.reference_repo import (
    get_all_references,
    get_reference,
    get_references,
)
from refcheck.models.reference import Reference

router = APIRouter()
logger = logging.getLogger(__name__)


class ReferencesResponse(BaseModel):
    """Paginated reference list response."""

    references: list[Reference]
    total: int
    page: int
    per_page: int


class ConfirmMatchRequest(BaseModel):
    """Request to confirm/reject a PDF match."""

    confirmed: bool


class ConfirmMatchResponse(BaseModel):
    """Response after confirming a match."""

    reference_id: int
    pdf_status: str
    match_confidence: float
    match_method: str


@router.get(
    "/api/sessions/{session_id}/references",
    response_model=ReferencesResponse,
)
async def list_references(
    session_id: str,
    status: str = "all",
    sort: str = "id",
    page: int = 1,
    per_page: int = 50,
    db: DBSession = Depends(get_db),
) -> ReferencesResponse:
    """List all references for a session with filtering."""
    db_refs, total = get_references(db, session_id, status, page, per_page)
    refs = [db_to_reference(r) for r in db_refs]

    if sort == "status":
        refs = sorted(refs, key=lambda r: r.source_status)

    return ReferencesResponse(
        references=refs, total=total, page=page, per_page=per_page,
    )


@router.post(
    "/api/sessions/{session_id}/matches/{ref_id}/confirm",
    response_model=ConfirmMatchResponse,
)
async def confirm_match(
    session_id: str,
    ref_id: int,
    body: ConfirmMatchRequest,
    db: DBSession = Depends(get_db),
) -> ConfirmMatchResponse:
    """Confirm or reject a PDF match."""
    ref = get_reference(db, session_id, ref_id)
    if not ref:
        raise HTTPException(404, "Reference not found")

    method = "user_confirmed" if body.confirmed else "unmatched"
    return ConfirmMatchResponse(
        reference_id=ref_id,
        pdf_status="matched" if body.confirmed else "unmatched",
        match_confidence=1.0 if body.confirmed else 0.0,
        match_method=method,
    )


@router.post("/api/sessions/{session_id}/references/{ref_id}/upload-pdf")
async def upload_reference_pdf(
    session_id: str,
    ref_id: int,
    pdf: UploadFile,
    db: DBSession = Depends(get_db),
) -> dict[str, object]:
    """Upload a PDF for a specific reference."""
    if not pdf.filename or not pdf.filename.endswith(".pdf"):
        raise HTTPException(400, "File must be a PDF")

    return {
        "reference_id": ref_id,
        "pdf_status": "matched",
        "pdf_source": "user_upload",
        "match_confidence": 1.0,
    }


def load_references_for_session(
    db: DBSession, session_id: str,
) -> list[Reference]:
    """Load all references as Pydantic models (utility for other modules)."""
    db_refs = get_all_references(db, session_id)
    return [db_to_reference(r) for r in db_refs]
