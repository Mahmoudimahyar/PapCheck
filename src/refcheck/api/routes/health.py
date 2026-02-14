"""Health check endpoint."""

import logging

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session as DBSession
from sqlmodel import text

from refcheck.db.deps import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "ok"
    grobid: str = "unavailable"
    database: str = "disconnected"
    version: str = "3.0.0"
    cache: dict[str, dict[str, int]] | None = None


@router.get("/api/health", response_model=HealthResponse)
async def health_check(
    db: DBSession = Depends(get_db),
) -> HealthResponse:
    """Return service health status."""
    db_status = _check_database(db)
    grobid_status = await _check_grobid()
    cache_stats = _check_cache()
    overall = "ok" if db_status == "connected" else "degraded"
    return HealthResponse(
        status=overall,
        grobid=grobid_status,
        database=db_status,
        cache=cache_stats,
    )


def _check_database(db: DBSession) -> str:
    """Verify database connectivity."""
    try:
        db.exec(text("SELECT 1"))  # type: ignore[call-overload]
        return "connected"
    except Exception as exc:
        logger.error("Database health check failed: %s", exc)
        return "disconnected"


def _check_cache() -> dict[str, dict[str, int]] | None:
    """Get cache statistics."""
    try:
        from refcheck.utils.cache import get_cache_stats

        return get_cache_stats()
    except Exception:
        return None


async def _check_grobid() -> str:
    """Check GROBID service availability."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get("http://localhost:8070/api/isalive")
            if resp.status_code == 200:
                return "available"
            return "unavailable"
    except Exception:
        return "unavailable"
