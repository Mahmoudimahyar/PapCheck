"""Pipeline orchestrator: runs all 6 stages sequentially."""

import logging
from pathlib import Path

from refcheck.api.routes.events import close_event_stream, emit_event
from refcheck.api.routes.sessions import get_session_store
from refcheck.models.pipeline import PipelineEvent, PipelineState
from refcheck.services.stage_runners import (
    run_extract_claims,
    run_match,
    run_parse,
    run_report,
    run_resolve,
    run_verify,
)

logger = logging.getLogger(__name__)


async def run_pipeline(session_id: str, session_dir: Path) -> None:
    """Run the full V1 pipeline for a session (6 stages)."""
    state = PipelineState(session_id=session_id, status="running")
    _update_session_status(session_id, "running")
    try:
        state = await run_parse(session_id, session_dir, state)
        state = await run_extract_claims(session_id, state)
        state = await run_match(session_id, session_dir, state)
        state = await run_resolve(session_id, state)
        state = await run_verify(session_id, state)
        state = await run_report(session_id, session_dir, state)

        state = state.model_copy(update={"status": "complete"})
        await emit_event(session_id, PipelineEvent(
            status="pipeline_complete", message="Pipeline complete",
        ))
        _update_session_status(session_id, "complete")
    except Exception as exc:
        logger.error("Pipeline error for %s: %s", session_id, exc)
        state = state.model_copy(update={"status": "error"})
        await emit_event(session_id, PipelineEvent(
            status="error", message=str(exc),
        ))
        _update_session_status(session_id, "error")
    finally:
        await close_event_stream(session_id)


def _update_session_status(session_id: str, status: str) -> None:
    """Update session status in the shared store."""
    sessions = get_session_store()
    if session_id in sessions:
        sessions[session_id] = sessions[session_id].model_copy(
            update={"status": status},
        )
