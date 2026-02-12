"""Verification results endpoints (V1 stub)."""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class ResultsSummary(BaseModel):
    """Summary of verification results (V1)."""

    total: int = 0
    supported: int = 0
    partially_supported: int = 0
    not_supported: int = 0
    contradicted: int = 0
    cannot_verify: int = 0


@router.get("/api/sessions/{session_id}/results")
async def get_results(session_id: str) -> dict[str, object]:
    """Get verification results (V1 stub)."""
    return {
        "summary": ResultsSummary().model_dump(),
        "results": [],
        "total": 0,
        "page": 1,
        "per_page": 50,
    }
