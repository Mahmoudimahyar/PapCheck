"""Health check endpoint.

``GET /api/health`` reports database/GROBID/cache status plus the model
resolved for every LLM role (no API calls). ``?deep=true`` runs the LLM
preflight instead: one tiny real call per role, cached for 10 minutes.
V5.8: ``llm`` is "degraded" when a soft role runs on a fallback / is skipped;
``degraded_notices`` / ``actions`` say why and what to do (health_llm.py).
"""

import logging
import time

import httpx
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlmodel import Session as DBSession
from sqlmodel import text

from refcheck.api.routes.health_llm import (
    REQUIRED_ROLES,
    RoleHealth,
    check_models,
    decisions_status,
    degraded_notices,
    llm_overall,
    to_role_health,
)
from refcheck.db.deps import get_db
from refcheck.llm.roles import privacy_profile

__all__ = [
    "REQUIRED_ROLES", "HealthResponse", "RoleHealth", "decisions_status", "health_check",
    "llm_overall", "to_role_health",
]

router = APIRouter()
logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "ok"
    grobid: str = "unavailable"
    database: str = "disconnected"
    version: str = "3.0.0"
    cache: dict[str, dict[str, int]] | None = None
    # V5: LLM roles ("ok" | "degraded" | "unavailable" | "unknown")
    llm: str = "unknown"
    decisions_api: str = "unknown"  # available | unavailable | disabled | unknown
    privacy_profile: str = "standard"
    deep: bool = False
    models: dict[str, RoleHealth] = Field(default_factory=dict)
    # V5.8 degraded mode: one sentence per degraded role, and what the user can do
    degraded_notices: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)


@router.get("/api/health", response_model=HealthResponse)
async def health_check(
    deep: bool = Query(default=False, description="Probe every LLM role with a real call"),
    db: DBSession = Depends(get_db),
) -> HealthResponse:
    """Return service health status."""
    db_status = _check_database(db)
    grobid_status = await _check_grobid()
    cache_stats = _check_cache()
    overall = "ok" if db_status == "connected" else "degraded"
    models = await check_models(deep)
    notices, actions = degraded_notices(models)
    return HealthResponse(
        status=overall,
        grobid=grobid_status,
        database=db_status,
        cache=cache_stats,
        llm=llm_overall(models),
        decisions_api=decisions_status(models.get("screen")),
        privacy_profile=_privacy_profile(),
        deep=deep,
        models=models,
        degraded_notices=notices,
        actions=actions,
    )


def _privacy_profile() -> str:
    try:
        return privacy_profile()
    except Exception as exc:
        logger.warning("Could not read privacy profile: %s", exc)
        return "unknown"


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


_GROBID_URL = "http://127.0.0.1:8070/api/isalive"  # not "localhost": on Windows a refused
# connection is retried on ::1 and 127.0.0.1, adding ~2.6 s to every health call
_GROBID_TTL_S = 30.0
_grobid_cache: tuple[float, str] | None = None


async def _check_grobid() -> str:
    """Check GROBID service availability (cached for 30 s)."""
    global _grobid_cache  # noqa: PLW0603
    now = time.monotonic()
    if _grobid_cache is not None and now - _grobid_cache[0] < _GROBID_TTL_S:
        return _grobid_cache[1]
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            resp = await client.get(_GROBID_URL)
            status = "available" if resp.status_code == 200 else "unavailable"
    except httpx.HTTPError:
        status = "unavailable"
    _grobid_cache = (now, status)
    return status
