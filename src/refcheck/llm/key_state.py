"""Persisted 'this key is exhausted' markers (fingerprints only, never keys).

File: ``REFCHECK_KEY_STATE_FILE`` (default ``~/.refcheck/state/key_state.json``;
set it to an empty string to disable persistence). Markers expire after
``REFCHECK_EXHAUSTED_KEY_TTL_HOURS`` (default 6) so a topped-up key is retried.
"""

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_DEFAULT_TTL_HOURS = 6.0


def fingerprint(key: str) -> str:
    """Non-reversible short identifier for a key value."""
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _path() -> Path | None:
    raw = os.environ.get("REFCHECK_KEY_STATE_FILE")
    if raw is None:
        return Path.home() / ".refcheck" / "state" / "key_state.json"
    return Path(raw) if raw.strip() else None


def _ttl_seconds() -> float:
    try:
        hours = float(os.environ.get("REFCHECK_EXHAUSTED_KEY_TTL_HOURS", _DEFAULT_TTL_HOURS))
    except ValueError:
        hours = _DEFAULT_TTL_HOURS
    return hours * 3600.0


def _read(path: Path) -> dict[str, dict[str, object]]:
    """Load live (unexpired) markers; unreadable files count as empty."""
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    now = time.time()
    live: dict[str, dict[str, object]] = {}
    for fp, entry in raw.items():
        until = entry.get("until") if isinstance(entry, dict) else None
        if isinstance(until, (int, float)) and until > now:
            live[str(fp)] = {str(k): v for k, v in entry.items()}
    return live


def is_marked(key: str) -> bool:
    """True if this key was marked exhausted and the marker has not expired."""
    return marked_reason(key) is not None


def marked_reason(key: str) -> str | None:
    """Why a live marker exists for this key ("billing", "auth", ...), else None."""
    path = _path()
    if path is None:
        return None
    with _lock:
        entry = _read(path).get(fingerprint(key))
    if entry is None:
        return None
    return str(entry.get("reason") or "exhausted")


def mark(key: str, provider: str, env_name: str, reason: str) -> None:
    """Persist an exhausted marker for a key (best effort)."""
    path = _path()
    if path is None:
        return
    with _lock:
        data = _read(path)
        data[fingerprint(key)] = {
            "provider": provider, "env": env_name, "reason": reason[:80],
            "until": time.time() + _ttl_seconds(),
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=1), encoding="utf-8")
        except OSError as exc:
            logger.debug("Could not persist key state: %s", exc)


def clear() -> None:
    """Delete all persisted markers."""
    path = _path()
    if path is None:
        return
    with _lock:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            logger.debug("Could not clear key state: %s", exc)
