"""Concurrent claim verification with timeout/error isolation and progress tracking."""

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable

from refcheck.models.claim import Claim
from refcheck.models.reference import Reference
from refcheck.models.verification import VerificationResult
from refcheck.services.progress import ProgressSnapshot, ProgressTracker

logger = logging.getLogger(__name__)

# Pairs verified at once; each pair makes at most a few sequential LLM calls and
# provider semaphores in refcheck.llm cap the real request concurrency.
DEFAULT_MAX_CONCURRENT = 12
# Per-pair time budget (seconds) handed to every LLM call of the pair.
CLAIM_TIMEOUT_SECONDS = 180
# The hard per-pair timeout is the budget plus this grace (the cascade enforces
# the budget itself; this only catches hangs).
TIMEOUT_GRACE_SECONDS = 30

VerifyFn = Callable[[Claim, Reference], Awaitable[VerificationResult]]
ProgressCb = Callable[[ProgressSnapshot], Awaitable[None]]
FailureFn = Callable[[Claim, Reference, str], VerificationResult]


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    try:
        value = int(float(raw)) if raw else default
    except ValueError:
        logger.warning("Ignoring %s=%r (not a number)", name, raw)
        return default
    return value if value > 0 else default


def get_max_concurrent() -> int:
    return _env_int("REFCHECK_MAX_CONCURRENT_CLAIMS", DEFAULT_MAX_CONCURRENT)


def get_claim_budget() -> int:
    """Per-pair time budget (env REFCHECK_CLAIM_TIMEOUT_SECONDS, default 180)."""
    return _env_int("REFCHECK_CLAIM_TIMEOUT_SECONDS", CLAIM_TIMEOUT_SECONDS)


async def verify_claims_concurrent(
    pairs: list[tuple[Claim, Reference]],
    verify_fn: VerifyFn,
    max_concurrent: int | None = None,
    timeout_seconds: int | None = None,
    progress_callback: ProgressCb | None = None,
    on_failure: FailureFn | None = None,
) -> list[VerificationResult]:
    """Run ``verify_fn`` for every pair (bounded concurrency), results in pair order.

    A pair that times out or raises becomes a cannot_verify/llm_error result
    (built by ``on_failure`` when given, so it can keep the pair's coverage).
    """
    if not pairs:
        return []
    limit = max_concurrent or get_max_concurrent()
    timeout = timeout_seconds or get_claim_budget() + TIMEOUT_GRACE_SECONDS
    semaphore = asyncio.Semaphore(limit)
    tracker = ProgressTracker(total=len(pairs), stage_name="verify_claims")
    results: list[VerificationResult | None] = [None] * len(pairs)
    failure = on_failure or _default_failure

    async def _process_one(index: int, claim: Claim, ref: Reference) -> None:
        async with semaphore:
            results[index] = await _safe_verify(index, claim, ref, verify_fn, timeout, failure)
            snapshot = tracker.tick()
            if progress_callback:
                try:
                    await progress_callback(snapshot)
                except Exception:  # a UI/SSE problem must never fail verification
                    logger.warning("Progress cb failed for pair %d", index)

    await asyncio.gather(*[_process_one(i, c, r) for i, (c, r) in enumerate(pairs)])
    return [
        r if r is not None else failure(pairs[i][0], pairs[i][1], "internal error")
        for i, r in enumerate(results)
    ]


async def _safe_verify(
    index: int, claim: Claim, ref: Reference, verify_fn: VerifyFn, timeout: int,
    failure: FailureFn,
) -> VerificationResult:
    """Verify a single pair with timeout and error isolation."""
    try:
        return await asyncio.wait_for(verify_fn(claim, ref), timeout=timeout)
    except TimeoutError:
        logger.error("Pair %d (claim %d / ref %d) timed out after %ds",
                     index, claim.id, ref.id, timeout)
        return failure(claim, ref, f"Verification timed out after {timeout}s")
    except Exception as exc:  # isolate one pair's bug from the whole stage
        logger.exception("Pair %d (claim %d / ref %d) failed", index, claim.id, ref.id)
        return failure(claim, ref, f"Verification failed due to an internal error "
                                   f"({type(exc).__name__})")


def _default_failure(claim: Claim, ref: Reference, reason: str) -> VerificationResult:
    return VerificationResult(
        claim_id=claim.id, reference_id=ref.id, verdict="cannot_verify", confidence=0.0,
        reasoning=reason, cannot_verify_reason="llm_error", tier=1,
    )
