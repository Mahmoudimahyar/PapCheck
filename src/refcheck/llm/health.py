"""Preflight: one tiny real call per role; failing models fall back.

Used before stage 5 and by ``/api/health?deep=true``. Results are cached
for ``REFCHECK_PREFLIGHT_TTL_SECONDS`` (default 600). Hard failures
(billing/auth/404) mark the model unavailable for the process, so the real
calls that follow use the same fallback the preflight found. V5.8: a role that
ends on a degraded fallback (or with no model) is recorded (llm.degradation) on
the caller's CostTracker, even on a cache hit; only HARD_ROLES (the verifier)
make ``require_roles`` raise.
"""

import asyncio
import logging
import os
import time
from collections.abc import Mapping, Sequence

from refcheck.llm import keys
from refcheck.llm.cost_tracker import CostTracker
from refcheck.llm.degradation import Degradation
from refcheck.llm.degradation import clear as clear_degradation
from refcheck.llm.degradation import record as record_degradation
from refcheck.llm.errors import LLMError, short_error
from refcheck.llm.probe import PreflightReply, probe_model
from refcheck.llm.role_checks import PreflightError, failed_roles, hard_failed_roles
from refcheck.llm.roles import (
    RoleStatus,
    assess_degradation,
    mark_available,
    mark_unavailable,
    privacy_profile,
    resolve_role,
    role_candidates,
    static_failures,
    status_for,
    with_degradation,
)
from refcheck.llm.types import ALL_ROLES, Role

logger = logging.getLogger(__name__)

__all__ = [
    "PreflightError", "PreflightReply", "clear_preflight_cache", "failed_roles",
    "hard_failed_roles", "preflight", "probe_model", "require_roles",
]

_DEFAULT_TTL_S = 600.0
Probed = tuple[RoleStatus, Degradation | None]
_cache: dict[tuple[str, ...], tuple[float, dict[str, Probed]]] = {}


def _ttl() -> float:
    try:
        return float(os.environ.get("REFCHECK_PREFLIGHT_TTL_SECONDS", _DEFAULT_TTL_S))
    except ValueError:
        return _DEFAULT_TTL_S


def clear_preflight_cache() -> None:
    """Forget cached preflight results."""
    _cache.clear()


def _finish(status: RoleStatus, item: Degradation | None) -> Probed:
    if item is None:
        clear_degradation(status.role)  # recovered (or never degraded)
    return with_degradation(status, item), item


async def _probe_role(role: Role, tracker: CostTracker | None, timeout: float) -> Probed:
    tried: list[str] = []
    failures: list[tuple[str, str | None, str]] = []  # (model, error kind, text)
    candidates = [c.id for c in role_candidates(role)]
    for model_id in candidates:  # a fresh probe re-tests models a past probe benched
        mark_available(model_id, soft_only=True)
    while True:
        spec = resolve_role(role, exclude=tried)
        errors = "; ".join(f"{m}: {t}" for m, _, t in failures)
        if spec is None:
            base = status_for(role)
            status = base.model_copy(update={
                "model_id": None, "litellm_id": None, "provider": None, "display_name": None,
                "available": False, "probed": bool(tried), "probe_ok": False if tried else None,
                "reason": errors or base.reason, "tried": tried, "checked_at": time.time(),
            })
            return _finish(status, assess_degradation(role, None, _with_static(role, failures)))
        start = time.perf_counter()
        try:
            await asyncio.wait_for(probe_model(spec, role, tracker, timeout), timeout + 5)
        except (LLMError, TimeoutError) as exc:
            kind = exc.kind if isinstance(exc, LLMError) else "timeout"
            detail = f"{kind}: {short_error(exc, 200)}"
            failures.append((spec.id, kind, detail))
            tried.append(spec.id)
            # Soft failures (timeout, bad request, invalid JSON, refusal) bench the model
            # until the next probe so the real calls use the fallback this probe found.
            hard = isinstance(exc, LLMError) and exc.is_hard
            mark_unavailable(spec.id, detail, ttl_s=None if hard else _ttl())
            logger.warning("Preflight %s: %s failed: %s", role, spec.id, detail)
            continue
        status = RoleStatus(
            role=role, model_id=spec.id, litellm_id=spec.litellm_id, provider=spec.provider,
            display_name=spec.label, reasoning_effort=spec.reasoning_effort, available=True,
            reason=errors or None, fallback_index=candidates.index(spec.id),
            candidates=candidates, privacy_profile=privacy_profile(), probed=True,
            probe_ok=True, latency_ms=int((time.perf_counter() - start) * 1000),
            checked_at=time.time(), tried=tried,
        )
        return _finish(status, assess_degradation(role, spec, _with_static(role, failures)))


def _with_static(role: Role, failures: list[tuple[str, str | None, str]]
                 ) -> list[tuple[str, str | None, str]]:
    """Probe failures, then why the untried candidates were skipped (exhausted key...)."""
    return [*failures, *static_failures(role_candidates(role))]


def _cache_key(roles: Sequence[Role]) -> tuple[str, ...]:
    suffixes = ("_MODEL", "_EFFORT", "_ENABLED", "_FALLBACKS")
    overrides = sorted(f"{k}={v}" for k, v in os.environ.items()
                       if k.startswith("REFCHECK_") and k.endswith(suffixes))
    return (privacy_profile(), *roles, *overrides)


def _revive_if_persistent(wanted: Sequence[Role], hit: Mapping[str, Probed] | None) -> bool:
    """Re-test exhausted keys / hard-benched models when a role is down for a persistent
    cause (no credits, bad key): the user may have fixed it since. True if revived."""
    persistent = (any(item is not None and item.persistent for _, item in hit.values())
                  if hit is not None else any(status_for(r).persistent for r in wanted))
    if not persistent:
        return False
    keys.revive_exhausted()
    for role in wanted:
        for spec in role_candidates(role):
            mark_available(spec.id)
    return True


async def preflight(
    roles: Sequence[Role] | None = None,
    *,
    force: bool = False,
    cost_tracker: CostTracker | None = None,
    timeout: float = 45.0,
    retry_exhausted: bool = False,
) -> dict[str, RoleStatus]:
    """Probe each role's resolved model (falling back on failure).

    ``retry_exhausted`` (the user's live check): a role down for a persistent cause is
    re-probed with its exhausted keys / benched models revived (credits may be back).
    """
    wanted: tuple[Role, ...] = tuple(roles) if roles else ALL_ROLES
    key = _cache_key(wanted)
    hit = _cache.get(key)
    if retry_exhausted and _revive_if_persistent(wanted, hit[1] if hit else None):
        force = True
    if hit is not None and not force and time.monotonic() - hit[0] < _ttl():
        probed = hit[1]
    else:
        results = await asyncio.gather(*[_probe_role(r, cost_tracker, timeout) for r in wanted])
        probed = {status.role: (status, item) for status, item in results}
        _cache[key] = (time.monotonic(), probed)
    for _, item in probed.values():
        if item is not None:  # every run that relies on this preflight learns it degraded
            record_degradation(item, cost_tracker)
    return {role: status for role, (status, _) in probed.items()}


async def require_roles(
    roles: Sequence[Role],
    *,
    force: bool = False,
    cost_tracker: CostTracker | None = None,
    timeout: float = 45.0,
) -> dict[str, RoleStatus]:
    """Preflight ``roles``; raise PreflightError only if a HARD role has no working model.

    Soft roles degrade instead (recorded on ``cost_tracker`` and process-wide).
    """
    statuses = await preflight(roles, force=force, cost_tracker=cost_tracker, timeout=timeout)
    failed = hard_failed_roles(statuses)
    if failed:
        details = "; ".join(f"{r}: {statuses[r].reason}" for r in failed)
        raise PreflightError(f"no working model for role(s) {', '.join(failed)} — {details}")
    return statuses
