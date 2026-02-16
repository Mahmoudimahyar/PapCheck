"""LLM response caching helpers."""

import json
import logging
from typing import TypeVar

from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def check_llm_cache(
    template: str,
    variables: dict[str, str],
    model: str,
    output_model: type[T],
) -> T | None:
    """Check the LLM cache for a matching response."""
    try:
        from refcheck.utils.cache import get_cached_llm_response

        cached_json = get_cached_llm_response(template, variables, model)
        if cached_json is None:
            return None
        parsed = json.loads(cached_json)
        result = output_model.model_validate(parsed)
        logger.info("LLM cache HIT: template=%s", template)
        return result
    except Exception:
        return None


def store_llm_cache(
    template: str,
    variables: dict[str, str],
    model: str,
    response_json: str,
) -> None:
    """Store a valid LLM response in the cache."""
    try:
        from refcheck.utils.cache import cache_llm_response

        cache_llm_response(template, variables, model, response_json)
    except Exception:
        logger.debug("Failed to cache LLM response", exc_info=True)
