"""Disk-based caching for API responses, LLM calls, and PDF text.

Uses diskcache for persistent file-based caching. Separate caches
for different categories (API, LLM, PDF) with independent TTLs.
"""

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import TypeVar

import diskcache
from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_CACHE_DIR = Path(os.getenv(
    "REFCHECK_CACHE_DIR",
    str(Path.home() / ".refcheck" / "cache"),
))

# TTLs in seconds
_API_TTL = int(os.getenv("REFCHECK_API_CACHE_TTL", str(86400)))  # 24h
_LLM_TTL = int(os.getenv("REFCHECK_LLM_CACHE_TTL", str(604800)))  # 7d
_PDF_TTL = int(os.getenv("REFCHECK_PDF_CACHE_TTL", str(2592000)))  # 30d

_caches: dict[str, diskcache.Cache] = {}


def _get_cache(name: str) -> diskcache.Cache:
    """Get or create a named cache directory."""
    if name not in _caches:
        cache_path = _CACHE_DIR / name
        cache_path.mkdir(parents=True, exist_ok=True)
        _caches[name] = diskcache.Cache(str(cache_path))
        logger.info("Cache '%s' opened at %s", name, cache_path)
    return _caches[name]


def _make_key(prefix: str, data: str) -> str:
    """Create a deterministic cache key from a prefix and data string."""
    h = hashlib.sha256(data.encode()).hexdigest()[:16]
    return f"{prefix}:{h}"


def cache_api_response(
    endpoint: str, params: dict[str, str], response: str,
) -> None:
    """Cache an API response string (JSON or text)."""
    key = _make_key(endpoint, json.dumps(params, sort_keys=True))
    cache = _get_cache("api")
    cache.set(key, response, expire=_API_TTL)


def get_cached_api_response(
    endpoint: str, params: dict[str, str],
) -> str | None:
    """Retrieve a cached API response, or None if not cached."""
    key = _make_key(endpoint, json.dumps(params, sort_keys=True))
    cache = _get_cache("api")
    result = cache.get(key)
    if result is not None:
        logger.debug("Cache HIT: %s", key)
        return str(result)
    return None


def cache_llm_response(
    template: str,
    variables: dict[str, str],
    model: str,
    response_json: str,
) -> None:
    """Cache an LLM response (serialized JSON)."""
    data = json.dumps(
        {"template": template, "vars": variables, "model": model},
        sort_keys=True,
    )
    key = _make_key("llm", data)
    cache = _get_cache("llm")
    cache.set(key, response_json, expire=_LLM_TTL)


def get_cached_llm_response(
    template: str,
    variables: dict[str, str],
    model: str,
) -> str | None:
    """Retrieve a cached LLM response, or None if not cached."""
    data = json.dumps(
        {"template": template, "vars": variables, "model": model},
        sort_keys=True,
    )
    key = _make_key("llm", data)
    cache = _get_cache("llm")
    result = cache.get(key)
    if result is not None:
        logger.debug("LLM cache HIT: %s", key)
        return str(result)
    return None


def cache_pdf_text(pdf_path: str, text: str) -> None:
    """Cache extracted PDF text by file path."""
    key = _make_key("pdf", pdf_path)
    cache = _get_cache("pdf")
    cache.set(key, text, expire=_PDF_TTL)


def get_cached_pdf_text(pdf_path: str) -> str | None:
    """Retrieve cached PDF text, or None if not cached."""
    key = _make_key("pdf", pdf_path)
    cache = _get_cache("pdf")
    result = cache.get(key)
    if result is not None:
        logger.debug("PDF cache HIT: %s", key)
        return str(result)
    return None


def clear_all_caches() -> None:
    """Clear all caches (for testing or manual reset)."""
    for name, cache in _caches.items():
        cache.clear()
        logger.info("Cache '%s' cleared", name)


def get_cache_stats() -> dict[str, dict[str, int]]:
    """Return size statistics for all caches."""
    stats: dict[str, dict[str, int]] = {}
    for name in ("api", "llm", "pdf"):
        cache = _get_cache(name)
        stats[name] = {
            "entries": len(cache),
            "size_bytes": cache.volume(),
        }
    return stats
