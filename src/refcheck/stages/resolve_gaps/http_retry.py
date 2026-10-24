"""Back off and retry on HTTP 429 (Semantic Scholar, CrossRef, NCBI)."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

import httpx

logger = logging.getLogger(__name__)

_MAX_DELAY_SECONDS = 10.0


def _retry_after(resp: httpx.Response) -> float | None:
    value = resp.headers.get("Retry-After", "")
    try:
        return float(value) if value else None
    except ValueError:
        return None


async def send_with_backoff(
    send: Callable[[], Awaitable[httpx.Response]],
    retries: int = 2,
    base_delay: float = 1.0,
) -> httpx.Response:
    """Call `send` until it is not rate-limited (or retries run out)."""
    for attempt in range(retries + 1):
        resp = await send()
        if resp.status_code != 429 or attempt == retries:
            return resp
        delay = min(_retry_after(resp) or base_delay * 2 ** attempt, _MAX_DELAY_SECONDS)
        logger.info("HTTP 429 (rate limited); retrying in %.1fs", delay)
        await asyncio.sleep(delay)
    raise AssertionError("unreachable")  # loop always returns
