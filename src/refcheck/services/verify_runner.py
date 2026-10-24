"""Stage 5 & 6 runners: verify claims and detect missing citations."""

import logging
import time

from refcheck.api.routes.events import emit_event
from refcheck.db.engine import get_db_session
from refcheck.db.session_repo import update_session
from refcheck.llm.cost_tracker import CostTracker
from refcheck.models.pipeline import PipelineEvent, PipelineState
from refcheck.services.persist import persist_verifications, update_stage
from refcheck.services.progress import ProgressSnapshot
from refcheck.services.verify_outcome import (
    VerificationStageError,
    assess_verifications,
    describe_exception,
    format_cost,
    outcome_progress,
)

logger = logging.getLogger(__name__)


async def _verify_progress_cb(
    session_id: str, snapshot: ProgressSnapshot,
) -> None:
    """Emit SSE progress event for each completed verification."""
    await emit_event(session_id, PipelineEvent(
        stage=5, status="running",
        progress={
            "current": snapshot.current,
            "total": snapshot.total,
            "percent": snapshot.percent,
            "rate": snapshot.rate,
            "elapsed_seconds": snapshot.elapsed_seconds,
            "estimated_remaining_seconds": snapshot.estimated_remaining_seconds,
        },
        message=f"Verifying claims... {snapshot.current}/{snapshot.total}",
    ))


async def run_verify(
    session_id: str,
    state: PipelineState,
    cost_tracker: CostTracker | None = None,
) -> PipelineState:
    """Run Stage 5: Verify claims (LLM cascade).

    A raised exception (e.g. preflight found a role with no working model)
    is a stage *error*: the event carries the message, the stage is not
    marked done (so a resume re-runs it) and VerificationStageError stops
    the pipeline, which marks the session as error. If too many sourced
    pairs end in llm_error the results are still saved, but the stage event
    is "error" with the circuit-breaker message.
    """
    if not state.claims:
        await emit_event(session_id, PipelineEvent(
            stage=5, status="complete",
            message="No claims to verify (skipped)",
        ))
        update_stage(session_id, 5)
        return state.model_copy(update={"current_stage": 5})

    await emit_event(session_id, PipelineEvent(
        stage=5, status="running", message="Verifying claims...",
        progress={"current": 0, "total": float(len(state.claims))},
    ))
    start = time.time()
    tracker = cost_tracker or CostTracker()
    try:
        from refcheck.stages.verify_claims import verify_claims

        async def on_progress(snap: ProgressSnapshot) -> None:
            await _verify_progress_cb(session_id, snap)

        verifications = await verify_claims(
            state.claims, state.references,
            cost_tracker=tracker, progress_callback=on_progress,
        )
    except Exception as exc:
        message = f"Verification failed: {describe_exception(exc)}"
        logger.exception("Stage 5 failed for %s", session_id)
        await emit_event(session_id, PipelineEvent(
            stage=5, status="error", message=message,
            elapsed_seconds=round(time.time() - start, 1),
        ))
        raise VerificationStageError(message) from exc

    elapsed = round(time.time() - start, 1)
    persist_verifications(session_id, verifications)
    outcome = assess_verifications(verifications)
    summary = tracker.summary()
    cost_text = format_cost(summary)
    if outcome.breaker_tripped:
        logger.error("Session %s: %s", session_id, outcome.message)
        record_session_error(session_id, outcome.message)
        message = f"{outcome.message} Cost {cost_text}."
    else:
        message = f"{len(verifications)} verifications, {cost_text}"
    if summary.degraded:  # V5.8 G1: say which roles ran degraded and why
        message += " Degraded: " + " ".join(summary.degraded.values())
    await emit_event(session_id, PipelineEvent(
        stage=5, status="error" if outcome.breaker_tripped else "complete",
        message=message, elapsed_seconds=elapsed,
        progress=outcome_progress(outcome, summary),
    ))
    update_stage(session_id, 5)
    return state.model_copy(update={
        "verification_results": verifications, "current_stage": 5,
    })


def record_session_error(session_id: str, message: str) -> None:
    """Store a stage problem on the session without changing its status."""
    db = get_db_session()
    try:
        update_session(db, session_id, error_message=message)
    except Exception as exc:  # DB problems must not hide the stage result
        logger.warning("Could not record session error for %s: %s", session_id, exc)
    finally:
        db.close()


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
