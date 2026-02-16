"""Pipeline orchestrator: runs all 7 stages sequentially (V4)."""

import logging
from pathlib import Path

from refcheck.api.routes.events import close_event_stream, emit_event
from refcheck.db.engine import get_db_session
from refcheck.db.session_repo import update_session
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


async def run_pipeline(session_id: str, session_dir: Path) -> None:
    """Run the full V4 pipeline for a session (7 stages)."""
    state = PipelineState(session_id=session_id, status="running")
    _update_status(session_id, "running")

    cost_tracker = CostTracker()
    try:
        state = await run_parse(session_id, session_dir, state)
        state = await run_detect_citations(session_id, state)
        state = await run_match(session_id, session_dir, state)
        state = await run_resolve(session_id, state)
        state = await run_verify(session_id, state, cost_tracker)
        state = await run_missing_citations(session_id, state)
        state = await run_report(session_id, session_dir, state)

        await emit_event(session_id, PipelineEvent(
            status="pipeline_complete", message="Pipeline complete",
        ))
        _update_status(session_id, "complete")
    except Exception as exc:
        logger.error("Pipeline error for %s: %s", session_id, exc)
        await emit_event(session_id, PipelineEvent(
            status="error", message=str(exc),
        ))
        _update_status(session_id, "error", error_message=str(exc))
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
    _update_status(session_id, "running")

    state = PipelineState(
        session_id=session_id, status="running",
        current_stage=last_stage,
    )
    cost_tracker = CostTracker()
    try:
        if last_stage < 1:
            state = await run_parse(session_id, session_dir, state)
        if last_stage < 2:
            state = await run_detect_citations(session_id, state)
        if last_stage < 3:
            state = await run_match(session_id, session_dir, state)
        if last_stage < 4:
            state = await run_resolve(session_id, state)
        if last_stage < 5:
            state = await run_verify(session_id, state, cost_tracker)
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


def _update_status(
    session_id: str, status: str, error_message: str | None = None,
) -> None:
    """Update session status in the database."""
    db = get_db_session()
    try:
        kwargs: dict[str, object] = {"status": status}
        if error_message:
            kwargs["error_message"] = error_message
        update_session(db, session_id, **kwargs)
    finally:
        db.close()
