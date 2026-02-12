"""Report download endpoint."""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()
logger = logging.getLogger(__name__)

_REPORT_PATHS: dict[str, Path] = {}


@router.get("/api/sessions/{session_id}/report")
async def download_report(session_id: str) -> FileResponse:
    """Download the generated DOCX report."""
    report_path = _REPORT_PATHS.get(session_id)
    if not report_path or not report_path.exists():
        raise HTTPException(404, "Report not yet generated")

    return FileResponse(
        path=str(report_path),
        media_type=(
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document"
        ),
        filename=f"refcheck_report_{session_id}.docx",
    )


def get_report_store() -> dict[str, Path]:
    """Access report store (for pipeline runner and testing)."""
    return _REPORT_PATHS
