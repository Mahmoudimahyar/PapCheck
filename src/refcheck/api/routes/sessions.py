"""Session management endpoints."""

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile
from pydantic import BaseModel

from refcheck.models.pipeline import Session

router = APIRouter()
logger = logging.getLogger(__name__)

# Max upload size per file: 100 MB
_MAX_UPLOAD_BYTES = 100 * 1024 * 1024

# In-memory session store (MVP — replace with DB later)
_SESSIONS: dict[str, Session] = {}
_SESSION_DIRS: dict[str, Path] = {}
_BASE_DIR = Path.home() / ".refcheck" / "sessions"


class StartResponse(BaseModel):
    """Response for pipeline start."""

    message: str = "Pipeline started"


@router.post("/api/sessions", response_model=Session, status_code=201)
async def create_session(
    manuscript: UploadFile,
    pdfs: list[UploadFile] | None = None,  # noqa: B006
) -> Session:
    """Create a new verification session with uploaded files."""
    if not manuscript.filename or not manuscript.filename.endswith(".docx"):
        raise HTTPException(400, "Manuscript must be a .docx file")

    session_id = f"sess_{uuid.uuid4().hex[:12]}"
    session_dir = _BASE_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    # Save manuscript
    ms_path = session_dir / manuscript.filename
    content = await manuscript.read()
    ms_path.write_bytes(content)

    # Save PDFs
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

    session = Session(
        id=session_id,
        manuscript_filename=manuscript.filename or "unknown.docx",
        pdf_count=pdf_count,
    )
    _SESSIONS[session_id] = session
    _SESSION_DIRS[session_id] = session_dir

    logger.info("Created session %s with %d PDFs", session_id, pdf_count)
    return session


@router.get("/api/sessions/{session_id}", response_model=Session)
async def get_session(session_id: str) -> Session:
    """Get session status."""
    session = _SESSIONS.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return session


@router.post("/api/sessions/{session_id}/start", response_model=StartResponse)
async def start_pipeline(
    session_id: str,
    background_tasks: BackgroundTasks,
) -> StartResponse:
    """Start or resume the verification pipeline."""
    session = _SESSIONS.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    from refcheck.services.pipeline_runner import run_pipeline

    session_dir = _SESSION_DIRS[session_id]
    background_tasks.add_task(run_pipeline, session_id, session_dir)

    _SESSIONS[session_id] = session.model_copy(update={"status": "running"})
    return StartResponse()


def get_session_store() -> dict[str, Session]:
    """Access session store (for testing)."""
    return _SESSIONS


def get_session_dirs() -> dict[str, Path]:
    """Access session directories (for testing)."""
    return _SESSION_DIRS
