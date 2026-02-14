"""Rate limit retry logic for LLM API calls.

Detects 429 (rate limit) errors from litellm and retries with
exponential backoff. This prevents mass failures when many
verification calls hit the API concurrently.
"""

import asyncio
import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

_DEFAULT_MAX_RETRIES = 5
_BASE_WAIT_SECONDS = 10
_MAX_WAIT_SECONDS = 90


def _is_rate_limit_error(exc: Exception) -> bool:
    """Check if an exception is a rate limit (429) error from litellm."""
    # litellm raises litellm.exceptions.RateLimitError for 429s
    exc_type = type(exc).__name__
    if "RateLimit" in exc_type:
        return True
    # Also check the string representation for safety
    exc_str = str(exc).lower()
    return "rate_limit" in exc_str or "429" in exc_str


async def call_with_rate_limit_retry(
    sync_fn: Callable[..., str],
    model: str,
    messages: list[dict[str, str]],
    max_retries: int = _DEFAULT_MAX_RETRIES,
) -> str:
    """Call a sync LLM function with rate-limit-aware retries.

    On 429 errors, waits with exponential backoff before retrying.
    Non-rate-limit errors are raised immediately.

    Args:
        sync_fn: Synchronous completion function (_sync_completion).
        model: Model identifier string.
        messages: Chat messages list.
        max_retries: Maximum number of rate-limit retries.

    Returns:
        Raw LLM response string.

    Raises:
        The original exception if retries are exhausted or error
        is not a rate limit.
    """
    for attempt in range(max_retries + 1):
        try:
            return await asyncio.to_thread(sync_fn, model, messages)
        except Exception as exc:
            if _is_rate_limit_error(exc) and attempt < max_retries:
                wait = min(
                    _BASE_WAIT_SECONDS * (2 ** attempt),
                    _MAX_WAIT_SECONDS,
                )
                logger.warning(
                    "Rate limited (attempt %d/%d), waiting %ds: %s",
                    attempt + 1, max_retries + 1, wait,
                    str(exc)[:120],
                )
                await asyncio.sleep(wait)
            else:
                raise
    # Should not reach here, but satisfy type checker
    raise RuntimeError("Rate limit retries exhausted")
