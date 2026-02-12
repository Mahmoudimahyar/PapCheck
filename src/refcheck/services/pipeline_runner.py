"""Pipeline orchestrator: runs all stages sequentially."""

import asyncio
import logging
import time
from pathlib import Path

from refcheck.api.routes.events import close_event_stream, emit_event
from refcheck.api.routes.references import get_reference_store
from refcheck.api.routes.reports import get_report_store
from refcheck.api.routes.sessions import get_session_store
from refcheck.models.pipeline import PipelineEvent, PipelineState
from refcheck.services.match_applier import apply_matches
from refcheck.stages.generate_report import generate_report
from refcheck.stages.match_pdfs import match_pdfs
from refcheck.stages.parse_docx import parse_manuscript
from refcheck.stages.resolve_gaps import resolve_gaps

logger = logging.getLogger(__name__)


async def run_pipeline(session_id: str, session_dir: Path) -> None:
    """Run the full MVP pipeline for a session."""
    state = PipelineState(session_id=session_id, status="running")
    _update_session_status(session_id, "running")
    try:
        state = await _run_parse(session_id, session_dir, state)
        state = await _run_match(session_id, session_dir, state)
        state = await _run_resolve(session_id, state)
        state = await _run_report(session_id, session_dir, state)

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


async def _run_parse(
    session_id: str, session_dir: Path, state: PipelineState,
) -> PipelineState:
    """Run Stage 1: Parse DOCX."""
    await emit_event(session_id, PipelineEvent(
        stage=1, status="running", message="Parsing manuscript...",
    ))
    start = time.time()
    docx_files = list(session_dir.glob("*.docx"))
    if not docx_files:
        raise FileNotFoundError("No DOCX file found in session")

    manuscript = await asyncio.to_thread(parse_manuscript, docx_files[0])
    elapsed = time.time() - start

    ref_store = get_reference_store()
    ref_store[session_id] = manuscript.references
    await emit_event(session_id, PipelineEvent(
        stage=1, status="complete",
        message=f"{len(manuscript.references)} references extracted",
        elapsed_seconds=round(elapsed, 1),
    ))
    return state.model_copy(update={
        "manuscript": manuscript,
        "references": manuscript.references,
        "current_stage": 1,
    })


async def _run_match(
    session_id: str, session_dir: Path, state: PipelineState,
) -> PipelineState:
    """Run Stage 3: Match PDFs."""
    await emit_event(session_id, PipelineEvent(
        stage=3, status="running", message="Matching PDFs...",
    ))
    start = time.time()
    pdf_dir = session_dir / "pdfs"
    results = await asyncio.to_thread(match_pdfs, state.references, pdf_dir)
    elapsed = time.time() - start

    matched_count = sum(1 for r in results if r.match_method != "unmatched")
    needs_confirm = sum(1 for r in results if r.needs_user_confirmation)
    updated_refs = apply_matches(state.references, results)

    msg = f"{matched_count} PDFs matched"
    if needs_confirm:
        msg += f" ({needs_confirm} need confirmation)"

    ref_store = get_reference_store()
    ref_store[session_id] = updated_refs
    await emit_event(session_id, PipelineEvent(
        stage=3, status="complete", message=msg,
        elapsed_seconds=round(elapsed, 1),
    ))
    return state.model_copy(update={
        "match_results": results,
        "references": updated_refs,
        "current_stage": 3,
    })


async def _run_resolve(
    session_id: str, state: PipelineState,
) -> PipelineState:
    """Run Stage 4: Resolve gaps via APIs."""
    await emit_event(session_id, PipelineEvent(
        stage=4, status="running", message="Resolving gaps via APIs...",
    ))
    start = time.time()
    resolved = await resolve_gaps(state.references)
    elapsed = time.time() - start

    found = sum(1 for r in resolved if r.source_status == "found")
    not_found = sum(1 for r in resolved if r.source_status == "not_found")
    api_err = sum(1 for r in resolved if r.source_status == "api_error")

    parts = [f"{found} found"]
    if not_found:
        parts.append(f"{not_found} not found")
    if api_err:
        parts.append(f"{api_err} API errors")

    ref_store = get_reference_store()
    ref_store[session_id] = resolved
    await emit_event(session_id, PipelineEvent(
        stage=4, status="complete", message=", ".join(parts),
        elapsed_seconds=round(elapsed, 1),
    ))
    return state.model_copy(update={
        "references": resolved, "current_stage": 4,
    })


async def _run_report(
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

    report_store = get_report_store()
    report_store[session_id] = report_path
    await emit_event(session_id, PipelineEvent(
        stage=6, status="complete", message="Report ready",
        elapsed_seconds=round(elapsed, 1),
    ))
    return state.model_copy(update={"current_stage": 6})
