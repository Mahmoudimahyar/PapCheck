"""Per-provider API key rings with rotation (replaces key_manager).

Keys are read from the environment lazily and passed explicitly to litellm
(``api_key=``); os.environ is never mutated. A key that fails with a billing
or auth error is marked exhausted and the ring moves to the next key. The
exhausted marker is also persisted (as a truncated SHA-256 fingerprint, never
the key itself) so later processes skip a known-dead key pre-emptively.
"""

import logging
import os
import threading

from refcheck.llm import key_state

logger = logging.getLogger(__name__)

PROVIDER_ENV_KEYS: dict[str, list[str]] = {
    "anthropic": ["ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY_BACKUP"],
    "openai": ["OPENAI_API_KEY", "OPENAI_API_KEY_BACKUP"],
    "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
    "xai": ["XAI_API_KEY", "GROK_API_KEY"],
    "nvidia": ["NVIDIA_API_KEY", "NVIDIA_NIM_API_KEY"],
}

_lock = threading.Lock()
# provider -> list of (env var name, key value); values never leave this module
# except as the api_key argument of a provider call.
_rings: dict[str, list[tuple[str, str]]] = {}
_exhausted: dict[str, str] = {}  # fingerprint -> why ("billing", "auth", ...)


def _load(provider: str) -> list[tuple[str, str]]:
    """Read distinct keys for a provider from the environment (cached).

    An empty ring is re-read every time, so keys loaded from .env after the
    first lookup (e.g. load_dotenv at startup) are still picked up.
    """
    ring = _rings.get(provider)
    if not ring:
        ring = []
        seen: set[str] = set()
        for env_name in PROVIDER_ENV_KEYS.get(provider, [f"{provider.upper()}_API_KEY"]):
            value = os.environ.get(env_name, "").strip()
            if value and value not in seen:
                seen.add(value)
                ring.append((env_name, value))
        _rings[provider] = ring
        for env_name, value in ring:
            if (why := key_state.marked_reason(value)) is not None:
                _exhausted[key_state.fingerprint(value)] = why
                logger.info("Skipping %s (%s): marked exhausted earlier", env_name, provider)
    return ring


def _first_usable(provider: str) -> tuple[str, str] | None:
    for env_name, value in _load(provider):
        if key_state.fingerprint(value) not in _exhausted:
            return env_name, value
    return None


def get_key(provider: str) -> str | None:
    """Current usable key for a provider, or None when none is left."""
    with _lock:
        slot = _first_usable(provider)
    return slot[1] if slot else None


def current_slot(provider: str) -> str | None:
    """Env var NAME of the key in use (safe to log), or None."""
    with _lock:
        slot = _first_usable(provider)
    return slot[0] if slot else None


def has_key(provider: str) -> bool:
    """True when the provider still has a usable key."""
    return get_key(provider) is not None


def key_problem(provider: str) -> str | None:
    """Why a provider has no usable key: "no_key", or the last key's exhaustion kind
    ("billing" = no credits / quota, "auth" = rejected); None when a key is usable."""
    with _lock:
        ring = _load(provider)
        if not ring:
            return "no_key"
        if _first_usable(provider) is not None:
            return None
        return _exhausted.get(key_state.fingerprint(ring[-1][1]), "exhausted")


def key_count(provider: str) -> int:
    """Number of distinct keys configured for a provider."""
    with _lock:
        return len(_load(provider))


def rotate(provider: str, failed_key: str | None = None, reason: str = "") -> str | None:
    """Mark the failed (or current) key exhausted; return the next usable key.

    Idempotent under concurrency: if another task already rotated away from
    ``failed_key``, the current usable key is returned unchanged.
    """
    with _lock:
        if failed_key is None:
            slot = _first_usable(provider)
            failed_key = slot[1] if slot else None
        if failed_key is not None:
            fp = key_state.fingerprint(failed_key)
            if fp not in _exhausted:
                _exhausted[fp] = reason or "exhausted"
                env_name = next((n for n, v in _load(provider) if v == failed_key), "?")
                logger.warning("%s key %s exhausted (%s); rotating", provider, env_name, reason)
                key_state.mark(failed_key, provider, env_name, reason)
        nxt = _first_usable(provider)
    if nxt is None:
        logger.warning("No usable %s API key left", provider)
        return None
    return nxt[1]


def revive_exhausted() -> int:
    """Give every exhausted key another chance (e.g. after the user added credits).

    Clears the in-memory and persisted markers; a key that is still dead fails its
    next call (billing errors are not billed) and is marked again. Returns how many
    keys were revived.
    """
    with _lock:
        count = len(_exhausted)
        _exhausted.clear()
        key_state.clear()
    if count:
        logger.info("Re-testing %d exhausted API key(s)", count)
    return count


def reset_keys(clear_persisted: bool = False) -> None:
    """Forget cached rings/exhaustion (tests, or after editing .env)."""
    with _lock:
        _rings.clear()
        _exhausted.clear()
        if clear_persisted:
            key_state.clear()


def known_secrets() -> list[str]:
    """All loaded key values — ONLY for redacting error messages."""
    with _lock:
        return [value for ring in _rings.values() for _, value in ring]
