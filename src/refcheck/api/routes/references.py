"""Reference listing and management endpoints."""

import logging

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel

from refcheck.models.reference import Reference

router = APIRouter()
logger = logging.getLogger(__name__)

# Pipeline state store (populated by pipeline_runner)
_REFERENCE_STORE: dict[str, list[Reference]] = {}


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
) -> ReferencesResponse:
    """List all references for a session with filtering."""
    refs = _REFERENCE_STORE.get(session_id, [])

    # Filter by status
    if status != "all":
        refs = [r for r in refs if r.source_status == status]

    # Sort
    if sort == "status":
        refs = sorted(refs, key=lambda r: r.source_status)
    else:
        refs = sorted(refs, key=lambda r: r.id)

    total = len(refs)
    start = (page - 1) * per_page
    end = start + per_page

    return ReferencesResponse(
        references=refs[start:end],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.post(
    "/api/sessions/{session_id}/matches/{ref_id}/confirm",
    response_model=ConfirmMatchResponse,
)
async def confirm_match(
    session_id: str,
    ref_id: int,
    body: ConfirmMatchRequest,
) -> ConfirmMatchResponse:
    """Confirm or reject a PDF match."""
    refs = _REFERENCE_STORE.get(session_id, [])
    ref = next((r for r in refs if r.id == ref_id), None)
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


def get_reference_store() -> dict[str, list[Reference]]:
    """Access reference store (for pipeline runner and testing)."""
    return _REFERENCE_STORE
