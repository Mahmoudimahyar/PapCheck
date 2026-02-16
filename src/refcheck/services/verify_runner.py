"""Stage 5 & 6 runners: verify claims and detect missing citations."""

import logging
import time

from refcheck.api.routes.events import emit_event
from refcheck.llm.cost_tracker import CostTracker
from refcheck.models.pipeline import PipelineEvent, PipelineState
from refcheck.services.persist import persist_verifications, update_stage

logger = logging.getLogger(__name__)


async def run_verify(
    session_id: str,
    state: PipelineState,
    cost_tracker: CostTracker | None = None,
) -> PipelineState:
    """Run Stage 5: Verify claims (LLM). Gracefully skips on failure."""
    if not state.claims:
        await emit_event(session_id, PipelineEvent(
            stage=5, status="complete",
            message="No claims to verify (skipped)",
        ))
        update_stage(session_id, 5)
        return state.model_copy(update={"current_stage": 5})

    await emit_event(session_id, PipelineEvent(
        stage=5, status="running", message="Verifying claims...",
    ))
    start = time.time()
    try:
        from refcheck.stages.verify_claims import verify_claims

        tracker = cost_tracker or CostTracker()
        verifications = await verify_claims(
            state.claims, state.references, cost_tracker=tracker,
        )
        elapsed = time.time() - start
        persist_verifications(session_id, verifications)
        cost_summary = tracker.summary()
        await emit_event(session_id, PipelineEvent(
            stage=5, status="complete",
            message=f"{len(verifications)} verifications, ${cost_summary.total_usd:.2f}",
            elapsed_seconds=round(elapsed, 1),
        ))
        update_stage(session_id, 5)
        return state.model_copy(update={
            "verification_results": verifications, "current_stage": 5,
        })
    except Exception as exc:
        logger.error("Verification failed: %s", exc)
        await emit_event(session_id, PipelineEvent(
            stage=5, status="error",
            message=f"Verification failed: {exc}",
            elapsed_seconds=round(time.time() - start, 1),
        ))
        update_stage(session_id, 5)
        return state.model_copy(update={"current_stage": 5})


async def run_missing_citations(
    session_id: str, state: PipelineState,
) -> PipelineState:
    """Run Stage 6: Detect missing citations."""
    await emit_event(session_id, PipelineEvent(
        stage=6, status="running", message="Scanning for missing citations...",
    ))
    start = time.time()
    try:
        from refcheck.stages.detect_citations.missing_citation_detector import (
            detect_missing_citations,
        )

        if not state.manuscript:
            raise ValueError("No manuscript available")

        missing = detect_missing_citations(
            state.manuscript, state.all_citations,
        )
        elapsed = time.time() - start
        await emit_event(session_id, PipelineEvent(
            stage=6, status="complete",
            message=f"{len(missing)} potential missing citations",
            elapsed_seconds=round(elapsed, 1),
        ))
        update_stage(session_id, 6)
        return state.model_copy(update={
            "missing_citations": missing, "current_stage": 6,
        })
    except Exception as exc:
        logger.error("Missing citation detection failed: %s", exc)
        await emit_event(session_id, PipelineEvent(
            stage=6, status="error",
            message=f"Missing citation check failed: {exc}",
            elapsed_seconds=round(time.time() - start, 1),
        ))
        update_stage(session_id, 6)
        return state.model_copy(update={"current_stage": 6})
