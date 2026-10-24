"""Typed wrapper around the shared API disk cache for metadata records.

Cache failures (locked/corrupt diskcache) must never break resolution, so
every access is guarded and degrades to a cache miss.
"""

import logging
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from refcheck.utils.cache import cache_api_response, get_cached_api_response

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def load_record(kind: str, key: str, model: type[T]) -> T | None:
    """Return a cached record of `kind` for `key`, or None on miss/error."""
    try:
        raw = get_cached_api_response(kind, {"key": key})
    except Exception as exc:  # diskcache raises sqlite/OS errors
        logger.warning("API cache read failed (%s/%s): %s", kind, key, exc)
        return None
    if raw is None:
        return None
    try:
        return model.model_validate_json(raw)
    except ValidationError:
        logger.info("Ignoring stale cache entry %s/%s", kind, key)
        return None


def store_record(kind: str, key: str, record: BaseModel) -> None:
    """Cache a record; errors are logged and ignored."""
    try:
        cache_api_response(kind, {"key": key}, record.model_dump_json())
    except Exception as exc:  # diskcache raises sqlite/OS errors
        logger.warning("API cache write failed (%s/%s): %s", kind, key, exc)
