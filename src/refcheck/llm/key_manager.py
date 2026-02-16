"""Manage multiple Anthropic API keys with automatic rotation.

Reads ANTHROPIC_API_KEY and ANTHROPIC_API_KEY_BACKUP from the
environment at import time. When the active key's credits are
exhausted, rotate_anthropic_key() switches to the next available key.
"""

import logging
import os
import threading

logger = logging.getLogger(__name__)

_lock = threading.Lock()

# Snapshot keys at import time so rotation doesn't lose them
_ALL_KEYS: list[str] = []
_current_index: int = 0


def _init_keys() -> None:
    """Load all distinct Anthropic API keys from environment."""
    global _ALL_KEYS, _current_index  # noqa: PLW0603
    seen: set[str] = set()
    for env_var in ("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY_BACKUP"):
        key = os.environ.get(env_var, "").strip()
        if key and key not in seen:
            _ALL_KEYS.append(key)
            seen.add(key)
    _current_index = 0
    if _ALL_KEYS:
        logger.info("Loaded %d Anthropic API key(s)", len(_ALL_KEYS))


# Run on import so keys are captured before any rotation
_init_keys()


def get_anthropic_api_key() -> str:
    """Return the currently active Anthropic API key."""
    with _lock:
        if not _ALL_KEYS:
            return os.environ.get("ANTHROPIC_API_KEY", "")
        return _ALL_KEYS[_current_index]


def rotate_anthropic_key() -> str | None:
    """Switch to the next Anthropic API key.

    Returns the new key if rotation succeeded, None if no more
    keys are available.

    Thread-safe: concurrent calls won't skip or double-rotate.
    """
    global _current_index  # noqa: PLW0603
    with _lock:
        if len(_ALL_KEYS) <= 1:
            logger.warning("No backup Anthropic API key available")
            return None

        next_index = _current_index + 1
        if next_index >= len(_ALL_KEYS):
            logger.warning("All Anthropic API keys exhausted")
            return None

        _current_index = next_index
        new_key = _ALL_KEYS[_current_index]
        logger.info(
            "Rotated Anthropic key to slot %d of %d",
            _current_index + 1, len(_ALL_KEYS),
        )
        return new_key
