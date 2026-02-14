"""Stage 6: Report generation runner."""

import asyncio
import logging
import time
from pathlib import Path

from refcheck.api.routes.events import emit_event
from refcheck.models.pipeline import PipelineEvent, PipelineState
from refcheck.services.persist import persist_report_path, update_stage
from refcheck.stages.generate_report import generate_report

logger = logging.getLogger(__name__)


async def run_report(
    session_id: str, session_dir: Path, state: PipelineState,
) -> PipelineState:
    """Run Stage 6: Generate report."""
    await emit_event(session_id, PipelineEvent(
        stage=6, status="running", message="Generating report...",
    ))
    start = time.time()
    report_path = session_dir / f"refcheck_report_{session_id}.docx"
    await asyncio.to_thread(generate_report, state, report_path)
    elapsed = time.time() - start

    persist_report_path(session_id, str(report_path))
    await emit_event(session_id, PipelineEvent(
        stage=6, status="complete", message="Report ready",
        elapsed_seconds=round(elapsed, 1),
    ))
    update_stage(session_id, 6)
    return state.model_copy(update={"current_stage": 6})
