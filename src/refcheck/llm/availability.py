"""Which models are benched, and why (thread-safe, process-wide).

A hard failure (billing/auth/404) benches a model for the rest of the
process; a failed preflight probe benches it until the next probe (TTL), so
the real calls use the fallback that preflight found.
"""

import logging
import threading
import time

logger = logging.getLogger(__name__)

_lock = threading.Lock()
# model id -> (reason, monotonic expiry or None = rest of the process)
_unavailable: dict[str, tuple[str, float | None]] = {}


def _mark_locked(model_id: str) -> str | None:
    entry = _unavailable.get(model_id)
    if entry is not None and entry[1] is not None and time.monotonic() >= entry[1]:
        del _unavailable[model_id]  # a soft (preflight) mark expired
        return None
    return entry[0] if entry else None


def marked_reason(model_id: str) -> str | None:
    """Why a model is benched (None when it is not)."""
    with _lock:
        return _mark_locked(model_id)


def mark_unavailable(model_id: str, reason: str, ttl_s: float | None = None) -> None:
    """Disable a model: for the process (hard failure) or ``ttl_s`` seconds (failed probe)."""
    with _lock:
        current = _unavailable.get(model_id)
        if current is not None and current[1] is None and ttl_s is not None:
            return  # never downgrade a hard failure to a temporary one
        if current is None:
            logger.warning("Model %s marked unavailable: %s", model_id, reason)
        _unavailable[model_id] = (reason, None if ttl_s is None else time.monotonic() + ttl_s)


def mark_available(model_id: str, soft_only: bool = False) -> None:
    """Re-enable a model (``soft_only``: only clear a temporary probe mark)."""
    with _lock:
        entry = _unavailable.get(model_id)
        if entry is not None and (not soft_only or entry[1] is not None):
            del _unavailable[model_id]


def unavailable_models() -> dict[str, str]:
    """Snapshot of disabled models and reasons."""
    with _lock:
        return {mid: reason for mid in list(_unavailable)
                if (reason := _mark_locked(mid)) is not None}


def reset_availability() -> None:
    """Forget all hard-failure marks (tests / preflight force)."""
    with _lock:
        _unavailable.clear()
