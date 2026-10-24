"""Run one blocking provider call with keys, limits, retries and backoff.

Shared by chat completions, the Decisions API and embeddings. The sync
litellm function runs in a dedicated thread pool (Windows-safe; sized by
``REFCHECK_LLM_THREADS``, default 64, so the default asyncio executor does
not cap provider concurrency). Billing/auth
errors rotate to the provider's next key; 429/5xx/timeouts back off with
jitter; everything else is raised as LLMCallError.
"""

import asyncio
import functools
import logging
import os
import random
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

from refcheck.llm import keys
from refcheck.llm.errors import LLMCallError, classify_error, is_key_failure, short_error
from refcheck.llm.limits import provider_semaphore
from refcheck.llm.types import RETRYABLE

logger = logging.getLogger(__name__)

R = TypeVar("R")

_DEFAULT_MAX_ATTEMPTS = 4
_BASE_DELAY_S = 1.0
_MAX_DELAY_S = 20.0
_MIN_ATTEMPT_TIMEOUT_S = 1.0
_DEFAULT_THREADS = 64

_executor: ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()


def _llm_executor() -> ThreadPoolExecutor:
    """Shared pool for blocking provider calls (created lazily)."""
    global _executor  # noqa: PLW0603 - lazy process-wide singleton
    with _executor_lock:
        if _executor is None:
            try:
                size = max(4, int(os.environ.get("REFCHECK_LLM_THREADS", _DEFAULT_THREADS)))
            except ValueError:
                size = _DEFAULT_THREADS
            _executor = ThreadPoolExecutor(max_workers=size, thread_name_prefix="refcheck-llm")
        return _executor


def max_attempts() -> int:
    """Attempts per call for retryable errors (env REFCHECK_LLM_MAX_ATTEMPTS)."""
    try:
        return max(1, int(os.environ.get("REFCHECK_LLM_MAX_ATTEMPTS", _DEFAULT_MAX_ATTEMPTS)))
    except ValueError:
        return _DEFAULT_MAX_ATTEMPTS


def backoff_delay(attempt: int) -> float:
    """Exponential backoff with full jitter (attempt is 1-based)."""
    cap: float = min(_MAX_DELAY_S, _BASE_DELAY_S * float(2 ** max(0, attempt - 1)))
    jitter: float = random.uniform(0, cap / 2)  # noqa: S311 - jitter, not crypto
    return cap / 2 + jitter


def deadline_from(timeout: float | None) -> float | None:
    """Monotonic deadline for a wall-clock budget in seconds."""
    return None if timeout is None else time.monotonic() + timeout


def _attempt_timeout(cap: float, deadline: float | None, label: str) -> float:
    if deadline is None:
        return cap
    left = deadline - time.monotonic()
    if left < _MIN_ATTEMPT_TIMEOUT_S:
        raise LLMCallError(f"time budget exhausted before calling {label}", "timeout", label)
    return min(cap, left)


async def call_provider(
    fn: Callable[[str, float], R],
    *,
    provider: str,
    label: str,
    timeout: float,
    deadline: float | None = None,
    attempts: int | None = None,
) -> R:
    """Call ``fn(api_key, timeout_s)`` in a thread with retries.

    Args:
        fn: Blocking provider call taking the API key and per-attempt timeout.
        provider: Key ring / semaphore name ("openai", "anthropic", ...).
        label: Model id used in errors and logs.
        timeout: Per-attempt timeout cap in seconds.
        deadline: Optional monotonic deadline for the whole call incl. retries.
        attempts: Max attempts for retryable errors (default env/4).
    """
    limit = attempts or max_attempts()
    attempt = 0
    rotations = 0
    while True:
        key = keys.get_key(provider)
        if key is None:
            raise LLMCallError(f"no usable {provider} API key", "unavailable", label)
        per_call = _attempt_timeout(timeout, deadline, label)
        attempt += 1
        try:
            async with provider_semaphore(provider):
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(
                    _llm_executor(), functools.partial(fn, key, per_call))
        except Exception as exc:  # noqa: BLE001 - every provider error is classified below
            kind = classify_error(exc)
            detail = short_error(exc)
            if is_key_failure(exc, kind):
                nxt = keys.rotate(provider, failed_key=key, reason=kind)
                if nxt is not None and rotations < keys.key_count(provider):
                    rotations += 1
                    attempt -= 1  # a key switch is not a retry of the same request
                    continue
                raise LLMCallError(detail, kind, label) from exc
            if kind in RETRYABLE and attempt < limit:
                delay = backoff_delay(attempt)
                if deadline is None or time.monotonic() + delay + 1 < deadline:
                    logger.warning("%s %s (attempt %d/%d), retry in %.1fs: %s",
                                   label, kind, attempt, limit, delay, detail[:160])
                    await asyncio.sleep(delay)
                    continue
            raise LLMCallError(detail, kind, label) from exc
