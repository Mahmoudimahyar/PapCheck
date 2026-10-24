"""Pipeline orchestrator: runs all 7 stages sequentially (V4)."""

import logging
from pathlib import Path

from refcheck.api.routes.events import close_event_stream, emit_event
from refcheck.db.engine import get_db_session
from refcheck.db.session_repo import update_session
from refcheck.llm import degradation
from refcheck.llm.cost_tracker import CostTracker
from refcheck.models.pipeline import PipelineEvent, PipelineState
from refcheck.services.report_runner import run_report
from refcheck.services.stage_runners import (
    run_detect_citations,
    run_match,
    run_parse,
    run_resolve,
)
from refcheck.services.verify_runner import run_missing_citations, run_verify

logger = logging.getLogger(__name__)

# V5.8: roles that ran degraded in stage 5 (confirm on a same-family fallback, screen
# skipped, BM25-only retrieval), with cause and fix; read back by the report.
DEGRADATIONS_FILE = degradation.RUN_FILE


async def _verify(session_id: str, session_dir: Path, state: PipelineState,
                  cost_tracker: CostTracker) -> PipelineState:
    """Stage 5, then save which LLM roles ran degraded (even when the stage failed)."""
    try:
        return await run_verify(session_id, state, cost_tracker)
    finally:
        items = cost_tracker.degradations
        for item in items.values():
            logger.warning("Session %s ran degraded: %s", session_id, degradation.describe(item))
        if session_dir.is_dir():
            degradation.save(session_dir / DEGRADATIONS_FILE, items)


async def run_pipeline(session_id: str, session_dir: Path) -> None:
    """Run the full V4 pipeline for a session (7 stages)."""
    state = PipelineState(session_id=session_id, status="running")
    _update_status(session_id, "running", clear_error=True)
    _clear_stale_events(session_id)

    cost_tracker = CostTracker()
    try:
        state = await run_parse(session_id, session_dir, state, cost_tracker)
        state = await run_detect_citations(session_id, state)
        state = await run_match(session_id, session_dir, state)
        state = await run_resolve(session_id, state)
        state = await _verify(session_id, session_dir, state, cost_tracker)
        state = await run_missing_citations(session_id, state)
        state = await run_report(session_id, session_dir, state)

        await emit_event(session_id, PipelineEvent(
            status="pipeline_complete", message="Pipeline complete",
        ))
        _update_status(session_id, "complete")
    except Exception as exc:
        message = str(exc) or type(exc).__name__
        logger.error("Pipeline error for %s: %s", session_id, message)
        await emit_event(session_id, PipelineEvent(
            status="error", message=message,
        ))
        _update_status(session_id, "error", error_message=message)
    finally:
        await close_event_stream(session_id)


async def resume_pipeline(session_id: str) -> None:
    """Resume a pipeline from the last completed stage."""
    db = get_db_session()
    try:
        from refcheck.db.session_repo import get_session
        sess = get_session(db, session_id)
        if not sess:
            logger.error("Cannot resume: session %s not found", session_id)
            return
        session_dir = Path.home() / ".refcheck" / "sessions" / session_id
        last_stage = sess.current_stage
    finally:
        db.close()

    logger.info("Resuming session %s from stage %d", session_id, last_stage)
    _update_status(session_id, "running", clear_error=True)
    _clear_stale_events(session_id)

    state = PipelineState(
        session_id=session_id, status="running",
        current_stage=last_stage,
    )
    cost_tracker = CostTracker()
    try:
        if last_stage < 1:
            state = await run_parse(session_id, session_dir, state, cost_tracker)
        if last_stage < 2:
            state = await run_detect_citations(session_id, state)
        if last_stage < 3:
            state = await run_match(session_id, session_dir, state)
        if last_stage < 4:
            state = await run_resolve(session_id, state)
        if last_stage < 5:
            state = await _verify(session_id, session_dir, state, cost_tracker)
        if last_stage < 6:
            state = await run_missing_citations(session_id, state)
        if last_stage < 7:
            state = await run_report(session_id, session_dir, state)

        await emit_event(session_id, PipelineEvent(
            status="pipeline_complete", message="Pipeline complete",
        ))
        _update_status(session_id, "complete")
    except Exception as exc:
        logger.error("Pipeline resume error: %s", exc)
        await emit_event(session_id, PipelineEvent(
            status="error", message=str(exc),
        ))
        _update_status(session_id, "error", error_message=str(exc))
    finally:
        await close_event_stream(session_id)


def _clear_stale_events(session_id: str) -> None:
    """Clear old pipeline events before re-running."""
    db = get_db_session()
    try:
        from refcheck.db.event_repo import clear_events

        clear_events(db, session_id)
    except Exception as exc:
        logger.warning("Failed to clear old events: %s", exc)
    finally:
        db.close()


def _update_status(
    session_id: str,
    status: str,
    error_message: str | None = None,
    clear_error: bool = False,
) -> None:
    """Update session status (and error message) in the database.

    A new run clears the previous run's error; a stage that saved results
    but reported a problem (stage 5 circuit breaker) keeps its message.
    """
    db = get_db_session()
    try:
        kwargs: dict[str, object] = {"status": status}
        if error_message:
            kwargs["error_message"] = error_message
        elif clear_error:
            kwargs["error_message"] = None
        update_session(db, session_id, **kwargs)
    finally:
        db.close()
