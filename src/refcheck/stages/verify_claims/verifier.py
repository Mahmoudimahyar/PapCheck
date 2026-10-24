"""Stage 5: claim verification — V5 "screen -> verify -> judge" cascade.

Order: resolve each reference's source once -> preflight the LLM roles (only
when some pair has a source) -> retrieve a standard evidence pack per pair ->
screen pre-pass for all sourced pairs (Decisions API, high concurrency) ->
per pair: L2 verifier / L3 judge / L4 confirm within a per-pair time budget.
No-source pairs short-circuit with a classified reason and make no LLM calls.
Each pair's context lists the other references of its sentence (cocited.py).
"""

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable, Sequence

from pydantic import BaseModel, ConfigDict, Field

from refcheck.llm import CostTracker, Role
from refcheck.llm.health import PreflightError, failed_roles, hard_failed_roles, preflight
from refcheck.models.claim import Claim
from refcheck.models.reference import Reference
from refcheck.models.verification import VerificationResult
from refcheck.services.progress import ProgressSnapshot
from refcheck.stages.verify_claims.calibration import ScreenThresholds, load_thresholds
from refcheck.stages.verify_claims.cascade import focus_query, run_cascade
from refcheck.stages.verify_claims.cascade_helpers import build_result
from refcheck.stages.verify_claims.cocited import CoCitedRef, co_cited_map
from refcheck.stages.verify_claims.concurrent import get_claim_budget, verify_claims_concurrent
from refcheck.stages.verify_claims.credit import with_credit_panels
from refcheck.stages.verify_claims.duplicate_sources import inherit_duplicate_sources
from refcheck.stages.verify_claims.retriever import EvidencePack, bm25_pack, clean_query, retrieve
from refcheck.stages.verify_claims.screen import ScreenResult, run_screen
from refcheck.stages.verify_claims.verifier_converters import log_tier_stats
from refcheck.stages.verify_claims.verifier_helpers import (
    PairContext,
    ResolvedSource,
    annotate_source_fallback,
    build_pair_context,
    cannot_verify,
    resolve_source,
)

logger = logging.getLogger(__name__)

ProgressCb = Callable[[ProgressSnapshot], Awaitable[None]]
PairKey = tuple[int, int]
REQUIRED_ROLES: tuple[Role, ...] = ("verifier", "judge", "confirm")
_RETRIEVAL_CONCURRENCY = 16


class VerificationRun(BaseModel):
    """Shared state of one verify_claims call."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    tracker: CostTracker
    thresholds: ScreenThresholds
    budget: float
    sources: dict[int, ResolvedSource] = Field(default_factory=dict)
    contexts: dict[PairKey, PairContext] = Field(default_factory=dict)
    screens: dict[PairKey, ScreenResult] = Field(default_factory=dict)
    co_cited: dict[PairKey, list[CoCitedRef]] = Field(default_factory=dict)  # same sentence

    def failure_result(self, claim: Claim, ref: Reference, reason: str) -> VerificationResult:
        """llm_error result that keeps the pair's real coverage (circuit breaker)."""
        src = self.sources.get(ref.id)
        return cannot_verify(claim, ref, reason, src.coverage if src else "no_source",
                             cv_reason="llm_error")


async def verify_claims(
    claims: list[Claim],
    references: list[Reference],
    cost_tracker: CostTracker | None = None,
    progress_callback: ProgressCb | None = None,
) -> list[VerificationResult]:
    """Verify every claim-reference pair; raises PreflightError if a role is dead."""
    ref_by_id = {r.id: r for r in inherit_duplicate_sources(references)}
    pairs: list[tuple[Claim, Reference]] = []
    for claim in with_credit_panels(claims):  # a figure credit is judged on its panel text
        for ref_id in claim.reference_ids:
            if (ref := ref_by_id.get(ref_id)) is None:
                logger.warning("Ref %d not found for claim %d", ref_id, claim.id)
                continue
            pairs.append((claim, ref))
    run = VerificationRun(tracker=cost_tracker or CostTracker(), thresholds=load_thresholds(),
                          budget=float(get_claim_budget()),
                          co_cited=co_cited_map(claims, ref_by_id))
    await _resolve_sources(run, {ref.id: ref for _, ref in pairs})
    sourced = [(c, r) for c, r in pairs if run.sources[r.id].doc is not None]
    logger.info("Verifying %d pairs (%d with a source; screen %s, t_accept=%.3f from %s)",
                len(pairs), len(sourced), "on" if run.thresholds.enabled else "off",
                run.thresholds.t_accept, run.thresholds.source)
    if sourced:
        await _preflight(run)
        await _build_contexts(run, sourced)
        await _screen_all(run)
    results = await verify_claims_concurrent(pairs=pairs,
                                             verify_fn=lambda c, r: _verify_single(c, r, run),
                                             progress_callback=progress_callback,
                                             on_failure=run.failure_result)
    log_tier_stats(results)
    return results


async def _resolve_sources(run: VerificationRun, refs: dict[int, Reference]) -> None:
    async def one(ref: Reference) -> None:
        try:
            run.sources[ref.id] = await resolve_source(ref)
        except Exception as exc:  # a corrupt PDF must not fail the stage
            logger.exception("Could not load source for ref %d", ref.id)
            run.sources[ref.id] = ResolvedSource(
                coverage="full_text", cannot_verify_reason="pdf_scanned",
                detail=f"PDF could not be read ({type(exc).__name__})")

    await asyncio.gather(*[one(ref) for ref in refs.values()])


async def _preflight(run: VerificationRun) -> None:
    """One tiny call per role; only a dead verifier (HARD_ROLES) fails the stage (V5.8 G1)."""
    roles: list[Role] = list(REQUIRED_ROLES)
    if run.thresholds.enabled:
        roles.append("screen")
    statuses = await preflight(roles, cost_tracker=run.tracker)
    failed = failed_roles(statuses)
    hard = hard_failed_roles(statuses)
    if hard:
        details = "; ".join(f"{role}: {statuses[role].reason}" for role in hard)
        raise PreflightError(f"no working model for role(s) {', '.join(hard)} — {details}")
    if "screen" in failed:
        logger.warning("Screen disabled for this run (Decisions API unavailable: %s)",
                       statuses["screen"].reason)
        run.thresholds = run.thresholds.model_copy(update={"enabled": False})


async def _build_contexts(run: VerificationRun, pairs: Sequence[tuple[Claim, Reference]]) -> None:
    semaphore = asyncio.Semaphore(_RETRIEVAL_CONCURRENCY)

    async def one(claim: Claim, ref: Reference) -> None:
        doc = run.sources[ref.id].doc
        if doc is None:
            return
        query = focus_query(claim, clean_query(claim.extracted_claim or claim.manuscript_text))
        async with semaphore:
            try:
                pack: EvidencePack = await retrieve(query, doc, cost_tracker=run.tracker)
            except Exception:  # retrieval bug -> deterministic BM25 pack, never no evidence
                logger.exception("Retrieval failed for claim %d / ref %d", claim.id, ref.id)
                pack = bm25_pack(query, doc)
        try:
            run.contexts[(claim.id, ref.id)] = build_pair_context(
                claim, ref, doc, pack, run.co_cited.get((claim.id, ref.id)), run.sources)
        except Exception:  # one odd claim must not fail the stage (pair -> llm_error)
            logger.exception("Could not build context for claim %d / ref %d", claim.id, ref.id)

    await asyncio.gather(*[one(c, r) for c, r in pairs])


def _screen_concurrency() -> int:
    raw = os.environ.get("REFCHECK_SCREEN_CONCURRENCY", "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else 64


async def _screen_all(run: VerificationRun) -> None:
    """Fast pre-pass: the screen for every sourced pair (P(problem) kept for all)."""
    if not run.thresholds.enabled or not run.contexts:
        return
    semaphore = asyncio.Semaphore(_screen_concurrency())
    start = time.monotonic()

    async def one(key: PairKey, ctx: PairContext) -> None:
        async with semaphore:
            run.screens[key] = await run_screen(ctx, run.tracker)

    await asyncio.gather(*[one(k, c) for k, c in run.contexts.items()])
    errors = sum(1 for s in run.screens.values() if not s.ok)
    logger.info("Screen pre-pass: %d pairs in %.1fs (%d skipped on error)",
                len(run.screens), time.monotonic() - start, errors)


async def _verify_single(claim: Claim, ref: Reference, run: VerificationRun) -> VerificationResult:
    """Verify one pair: short-circuit unusable sources, else run the cascade."""
    src = run.sources.get(ref.id)
    ctx = run.contexts.get((claim.id, ref.id))
    if src is not None and src.doc is not None and ctx is None:
        return run.failure_result(claim, ref, "Evidence for this pair could not be prepared")
    if src is None or src.doc is None or ctx is None:
        return cannot_verify(claim, ref, src.detail if src else "No source text available",
                             src.coverage if src else "no_source",
                             cv_reason=src.cannot_verify_reason if src else None,
                             text_quality_score=src.quality_score if src else 0.0)
    screen = run.screens.get((claim.id, ref.id))
    start = time.monotonic()
    outcome = await run_cascade(ctx, screen, run.thresholds, deadline=start + run.budget,
                                cost_tracker=run.tracker)
    latency = int((time.monotonic() - start) * 1000) + (screen.latency_ms if screen else 0)
    # An abstract standing in for an unusable PDF must say so (M14, source_fallback).
    return annotate_source_fallback(
        build_result(ctx, screen, outcome, run.thresholds, latency), ctx.doc)
