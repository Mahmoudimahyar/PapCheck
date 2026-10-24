"""Reference listing and management endpoints."""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlmodel import Session as DBSession

from refcheck.db.converters import db_to_reference, db_to_reference_with_access
from refcheck.db.deps import get_db
from refcheck.db.reference_repo import (
    get_all_references,
    get_reference,
    get_references,
)
from refcheck.models.open_access import ReferenceWithAccess
from refcheck.models.reference import Reference
from refcheck.services.pdf_upload import (
    PdfUploadError,
    UploadPdfResponse,
    accept_reference_pdf,
)
from refcheck.services.reverifier import (
    RefreshMetadataResponse,
    refresh_reference_metadata,
    reverify_reference,
)
from refcheck.stages.resolve_gaps.link_generator import generate_reference_links

router = APIRouter()
logger = logging.getLogger(__name__)


class ReferencesResponse(BaseModel):
    """Paginated reference list response."""

    references: list[ReferenceWithAccess]  # Reference + free-full-text hint (oa_*)
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
    refs = [db_to_reference_with_access(r) for r in db_refs]

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


class ReferenceLinksResponse(BaseModel):
    """External links for a reference."""

    doi_url: str | None = None
    pubmed_url: str | None = None
    scholar_url: str | None = None
    pmc_url: str | None = None
    journal_url: str | None = None


@router.get(
    "/api/sessions/{session_id}/references/{ref_id}/links",
    response_model=ReferenceLinksResponse,
)
async def get_reference_links(
    session_id: str,
    ref_id: int,
    db: DBSession = Depends(get_db),
) -> ReferenceLinksResponse:
    """Generate download links for a reference."""
    db_ref = get_reference(db, session_id, ref_id)
    if not db_ref:
        raise HTTPException(404, "Reference not found")
    ref = db_to_reference(db_ref)
    links = generate_reference_links(
        ref.doi, ref.pmid, ref.title,
        pmc_id=ref.pmc_id, journal_url=ref.journal_url,
    )
    return ReferenceLinksResponse(**links)


@router.post(
    "/api/sessions/{session_id}/references/{ref_id}/upload-pdf",
    response_model=UploadPdfResponse,
)
async def upload_reference_pdf(
    session_id: str,
    ref_id: int,
    pdf: UploadFile,
    background_tasks: BackgroundTasks,
    db: DBSession = Depends(get_db),
) -> UploadPdfResponse:
    """Save a PDF for one reference, then re-verify its claims in background."""
    if not pdf.filename or not pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "File must be a PDF")
    content = await pdf.read()
    try:
        response, ref_updates = await accept_reference_pdf(
            db, session_id, ref_id, content,
        )
    except PdfUploadError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    if response.reverification_started:
        background_tasks.add_task(
            reverify_reference, session_id, ref_id,
            response.claims_to_reverify, ref_updates,
        )
    return response


@router.post(
    "/api/sessions/{session_id}/references/{ref_id}/refresh-metadata",
    response_model=RefreshMetadataResponse,
)
async def refresh_metadata_endpoint(
    session_id: str,
    ref_id: int,
    background_tasks: BackgroundTasks,
    db: DBSession = Depends(get_db),
) -> RefreshMetadataResponse:
    """Re-fetch abstract + open-access hint; re-verify claims if the abstract changed."""
    response = await refresh_reference_metadata(db, session_id, ref_id)
    if response is None:
        raise HTTPException(404, "Reference not found")
    if response.reverification_started:
        background_tasks.add_task(
            reverify_reference, session_id, ref_id, response.claims_to_reverify,
        )
    return response


def load_references_for_session(
    db: DBSession, session_id: str,
) -> list[Reference]:
    """Load all references as Pydantic models (utility for other modules)."""
    db_refs = get_all_references(db, session_id)
    return [db_to_reference(r) for r in db_refs]
