"""Per-provider concurrency limits (asyncio semaphores).

Env ``REFCHECK_<PROVIDER>_CONCURRENCY`` overrides the defaults (openai 32,
anthropic 16, others 8). Semaphores are created per running event loop so a
semaphore is never shared across loops (tests, repeated asyncio.run()).
"""

import asyncio
import logging
import os
import weakref

logger = logging.getLogger(__name__)

DEFAULT_LIMITS: dict[str, int] = {"openai": 32, "anthropic": 16}
OTHER_PROVIDER_LIMIT = 8

_by_loop: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Semaphore]]" = (
    weakref.WeakKeyDictionary()
)


def provider_limit(provider: str) -> int:
    """Configured max in-flight requests for a provider."""
    default = DEFAULT_LIMITS.get(provider, OTHER_PROVIDER_LIMIT)
    raw = os.environ.get(f"REFCHECK_{provider.upper()}_CONCURRENCY")
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning("Invalid REFCHECK_%s_CONCURRENCY=%r; using %d",
                       provider.upper(), raw, default)
        return default


def provider_semaphore(provider: str) -> asyncio.Semaphore:
    """Semaphore bounding concurrent calls to one provider (current loop)."""
    loop = asyncio.get_running_loop()
    per_loop = _by_loop.setdefault(loop, {})
    sem = per_loop.get(provider)
    if sem is None:
        sem = asyncio.Semaphore(provider_limit(provider))
        per_loop[provider] = sem
    return sem


def reset_limits() -> None:
    """Drop all semaphores (tests / after changing env limits)."""
    _by_loop.clear()
