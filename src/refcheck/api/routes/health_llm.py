"""LLM part of ``/api/health``: per-role model status and degraded-mode notices.

Static resolution (no API calls), or a live preflight when ``deep``. V5.8:
only the verifier is required; any other role that lost its normal model is
"degraded" (confirm on a same-family fallback, screen skipped, BM25-only
retrieval) with the cause (billing / quota vs key vs network) and the fix.
"""

import logging
from collections.abc import Mapping

from pydantic import BaseModel, Field

from refcheck.llm.degradation import current, describe
from refcheck.llm.roles import RoleStatus, role_status
from refcheck.llm.types import HARD_ROLES

logger = logging.getLogger(__name__)

# Stage 5 stops without these; every other role only degrades the pipeline.
REQUIRED_ROLES: tuple[str, ...] = HARD_ROLES


class RoleHealth(BaseModel):
    """Resolved model and availability of one LLM role."""

    role: str
    model_id: str | None = None
    display_name: str | None = None
    provider: str | None = None
    reasoning_effort: str | None = None
    available: bool = False
    enabled: bool = True  # False when switched off on purpose (e.g. screen disabled)
    last_error: str | None = None
    fallback_index: int = 0
    candidates: list[str] = Field(default_factory=list)
    probed: bool = False
    probe_ok: bool | None = None
    latency_ms: int | None = None
    checked_at: float | None = None
    # V5.8 degraded mode
    degraded: bool = False
    degraded_mode: str | None = None  # fallback | skipped | bm25_only | unavailable
    cause: str | None = None  # billing | auth | no_key | not_found | network | rate_limit ...
    persistent: bool = False  # True: will not fix itself (add credits / fix the key)
    effect: str | None = None
    action: str | None = None


def to_role_health(status: RoleStatus) -> RoleHealth:
    """API view of a role status."""
    return RoleHealth(
        role=status.role, model_id=status.model_id, display_name=status.display_name,
        provider=status.provider, reasoning_effort=status.reasoning_effort,
        available=status.available,
        enabled=bool(status.candidates) or status.role in REQUIRED_ROLES,
        last_error=status.reason, fallback_index=status.fallback_index,
        candidates=status.candidates, probed=status.probed, probe_ok=status.probe_ok,
        latency_ms=status.latency_ms, checked_at=status.checked_at,
        degraded=status.degraded, degraded_mode=status.degraded_mode, cause=status.cause,
        persistent=status.persistent, effect=status.effect, action=status.action,
    )


def llm_overall(models: Mapping[str, RoleHealth]) -> str:
    """unavailable if the verifier is dead; degraded if any other enabled role is dead
    or runs degraded; else ok."""
    if not models:
        return "unknown"
    dead = {role for role, m in models.items() if m.enabled and not m.available}
    if dead & set(REQUIRED_ROLES):
        return "unavailable"
    degraded = any(m.degraded for m in models.values())
    return "degraded" if dead or degraded else "ok"


def decisions_status(screen: RoleHealth | None) -> str:
    """Decisions API (screen role) status."""
    if screen is None:
        return "unknown"
    if not screen.enabled:
        return "disabled"
    return "available" if screen.available else "unavailable"


async def check_models(deep: bool) -> dict[str, RoleHealth]:
    """Per-role status: static resolution, or a live preflight when ``deep``."""
    statuses: Mapping[str, RoleStatus]
    try:
        if deep:
            from refcheck.llm.health import preflight  # imports the litellm client

            # A live check re-tests keys that ran out of credit (the user may have topped up).
            statuses = await preflight(retry_exhausted=True)
        else:
            statuses = role_status()
    except Exception as exc:  # health must answer even when the LLM layer is broken
        logger.error("LLM role status check failed: %s", exc)
        return {}
    return {role: to_role_health(status) for role, status in statuses.items()}


def degraded_notices(models: Mapping[str, RoleHealth]) -> tuple[list[str], list[str]]:
    """(one sentence per degraded role, distinct user actions).

    Roles the status already reports come first; runtime-only degradations seen by
    this process (e.g. an embedding call that failed mid-run) are added after them.
    """
    notices: list[str] = []
    actions: list[str] = []
    runtime = current()
    for role, m in models.items():
        if m.degraded:
            item = runtime.get(role)
            notices.append(describe(item) if item is not None and item.mode == m.degraded_mode
                           else f"{role}: {m.effect or 'degraded'}.")
            if m.action and m.action not in actions:
                actions.append(m.action)
    for role, item in runtime.items():
        # A persistent cause (no credits, bad key) always shows in the role's status, so a
        # persistent entry for a role that now looks healthy is stale (it recovered).
        if role in models and (models[role].degraded or item.persistent):
            continue
        notices.append(describe(item))
        if item.action and item.action not in actions:
            actions.append(item.action)
    return notices, actions
