"""Disk caches for LLM responses and embeddings (diskcache).

Keys are SHA-256 hashes over everything that changes the answer (model,
effort, prompts, schema). Cache failures never break a call.
Env: ``REFCHECK_CACHE_DIR`` (default ~/.refcheck/cache),
``REFCHECK_LLM_CACHE_TTL`` seconds (default 7 days).
"""

import hashlib
import json
import logging
import os
import threading
from array import array
from pathlib import Path

import diskcache

logger = logging.getLogger(__name__)

_DEFAULT_TTL = 7 * 86400
_lock = threading.Lock()
_caches: dict[str, diskcache.Cache] = {}


def _cache(name: str) -> diskcache.Cache:
    root = Path(os.environ.get("REFCHECK_CACHE_DIR", str(Path.home() / ".refcheck" / "cache")))
    path = str(root / name)
    with _lock:
        cache = _caches.get(path)
        if cache is None:
            Path(path).mkdir(parents=True, exist_ok=True)
            cache = diskcache.Cache(path)
            _caches[path] = cache
    return cache


def _ttl() -> int:
    try:
        return int(os.environ.get("REFCHECK_LLM_CACHE_TTL", _DEFAULT_TTL))
    except ValueError:
        return _DEFAULT_TTL


def make_key(namespace: str, parts: dict[str, object]) -> str:
    """Deterministic key for a namespace and a JSON-able description."""
    blob = json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False)
    return f"{namespace}:{hashlib.sha256(blob.encode()).hexdigest()}"


def get_text(key: str) -> str | None:
    """Cached LLM response text, or None."""
    try:
        value = _cache("llm_v5").get(key)
    except Exception as exc:  # noqa: BLE001 - cache must never break a call
        logger.debug("LLM cache read failed: %s", exc)
        return None
    return value if isinstance(value, str) else None


def set_text(key: str, value: str) -> None:
    """Store an LLM response text."""
    try:
        _cache("llm_v5").set(key, value, expire=_ttl())
    except Exception as exc:  # noqa: BLE001
        logger.debug("LLM cache write failed: %s", exc)


def get_vector(key: str) -> list[float] | None:
    """Cached embedding vector, or None."""
    try:
        value = _cache("embeddings").get(key)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Embedding cache read failed: %s", exc)
        return None
    if isinstance(value, bytes) and value:
        return array("f", value).tolist()
    return None


def set_vector(key: str, vector: list[float]) -> None:
    """Store an embedding vector as float32 bytes (no TTL)."""
    try:
        _cache("embeddings").set(key, array("f", vector).tobytes())
    except Exception as exc:  # noqa: BLE001
        logger.debug("Embedding cache write failed: %s", exc)


def close_caches() -> None:
    """Close open cache handles (tests / shutdown)."""
    with _lock:
        for cache in _caches.values():
            cache.close()
        _caches.clear()
