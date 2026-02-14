"""Session management endpoints."""

import logging
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlmodel import Session as DBSession

from refcheck.db.deps import get_db
from refcheck.db.models import SessionDB
from refcheck.db.session_repo import (
    create_session as db_create_session,
)
from refcheck.db.session_repo import (
    delete_session as db_delete_session,
)
from refcheck.db.session_repo import (
    get_session as db_get_session,
)
from refcheck.db.session_repo import (
    list_sessions as db_list_sessions,
)
from refcheck.db.session_repo import (
    update_session as db_update_session,
)
from refcheck.models.pipeline import Session

router = APIRouter()
logger = logging.getLogger(__name__)

_BASE_DIR = Path.home() / ".refcheck" / "sessions"


class StartResponse(BaseModel):
    """Response for pipeline start."""

    message: str = "Pipeline started"


class SessionListResponse(BaseModel):
    """Paginated session list response."""

    sessions: list[Session]
    total: int
    page: int
    per_page: int


@router.post("/api/sessions", response_model=Session, status_code=201)
async def create_session(
    manuscript: UploadFile,
    pdfs: list[UploadFile] | None = None,  # noqa: B006
    db: DBSession = Depends(get_db),
) -> Session:
    """Create a new verification session with uploaded files."""
    if not manuscript.filename or not manuscript.filename.endswith(".docx"):
        raise HTTPException(400, "Manuscript must be a .docx file")

    session_id = f"sess_{uuid.uuid4().hex[:12]}"
    session_dir = _BASE_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    ms_path = session_dir / manuscript.filename
    content = await manuscript.read()
    ms_path.write_bytes(content)

    pdf_count = 0
    pdf_dir = session_dir / "pdfs"
    if pdfs:
        pdf_dir.mkdir(exist_ok=True)
        for pdf in pdfs:
            if pdf.filename:
                pdf_path = pdf_dir / pdf.filename
                pdf_content = await pdf.read()
                pdf_path.write_bytes(pdf_content)
                pdf_count += 1

    session_db = SessionDB(
        id=session_id,
        manuscript_filename=manuscript.filename or "unknown.docx",
        pdf_count=pdf_count,
        manuscript_path=str(ms_path),
        pdf_dir=str(pdf_dir),
    )
    db_create_session(db, session_db)
    logger.info("Created session %s with %d PDFs", session_id, pdf_count)

    return Session(
        id=session_id,
        manuscript_filename=manuscript.filename or "unknown.docx",
        pdf_count=pdf_count,
    )


@router.get("/api/sessions/{session_id}", response_model=Session)
async def get_session(
    session_id: str,
    db: DBSession = Depends(get_db),
) -> Session:
    """Get session status."""
    sess = db_get_session(db, session_id)
    if not sess:
        raise HTTPException(404, "Session not found")
    return Session(
        id=sess.id,
        status=sess.status,  # type: ignore[arg-type]
        created_at=sess.created_at,
        manuscript_filename=sess.manuscript_filename,
        pdf_count=sess.pdf_count,
    )


@router.get("/api/sessions", response_model=SessionListResponse)
async def list_sessions(
    page: int = 1,
    per_page: int = 10,
    db: DBSession = Depends(get_db),
) -> SessionListResponse:
    """List all sessions with pagination."""
    offset = (page - 1) * per_page
    sessions_db, total = db_list_sessions(db, limit=per_page, offset=offset)
    sessions = [
        Session(
            id=s.id,
            status=s.status,  # type: ignore[arg-type]
            created_at=s.created_at,
            manuscript_filename=s.manuscript_filename,
            pdf_count=s.pdf_count,
        )
        for s in sessions_db
    ]
    return SessionListResponse(
        sessions=sessions, total=total, page=page, per_page=per_page,
    )


@router.post(
    "/api/sessions/{session_id}/start", response_model=StartResponse,
)
async def start_pipeline(
    session_id: str,
    background_tasks: BackgroundTasks,
    db: DBSession = Depends(get_db),
) -> StartResponse:
    """Start or resume the verification pipeline."""
    sess = db_get_session(db, session_id)
    if not sess:
        raise HTTPException(404, "Session not found")

    from refcheck.services.pipeline_runner import run_pipeline

    session_dir = _BASE_DIR / session_id
    background_tasks.add_task(run_pipeline, session_id, session_dir)
    db_update_session(db, session_id, status="running")
    return StartResponse()


@router.delete("/api/sessions/{session_id}", status_code=200)
async def delete_session(
    session_id: str,
    db: DBSession = Depends(get_db),
) -> dict[str, str]:
    """Delete a session and all associated data and files."""
    deleted = db_delete_session(db, session_id)
    if not deleted:
        raise HTTPException(404, "Session not found")

    # Clean up files on disk
    session_dir = _BASE_DIR / session_id
    if session_dir.exists():
        shutil.rmtree(session_dir, ignore_errors=True)
        logger.info("Removed session directory: %s", session_dir)

    return {"message": f"Session {session_id} deleted"}
