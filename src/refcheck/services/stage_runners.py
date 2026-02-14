"""Individual stage runner functions for the pipeline."""

import asyncio
import logging
import time
from pathlib import Path

from refcheck.api.routes.events import emit_event
from refcheck.models.pipeline import PipelineEvent, PipelineState
from refcheck.services.match_applier import apply_matches
from refcheck.services.persist import (
    persist_claims,
    persist_manuscript_sections,
    persist_references,
    persist_verifications,
    update_stage,
)
from refcheck.stages.match_pdfs import match_pdfs
from refcheck.stages.parse_docx import parse_manuscript
from refcheck.stages.resolve_gaps import resolve_gaps

logger = logging.getLogger(__name__)


async def run_parse(
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

    persist_references(session_id, manuscript.references)
    persist_manuscript_sections(session_id, manuscript.sections)
    await emit_event(session_id, PipelineEvent(
        stage=1, status="complete",
        message=f"{len(manuscript.references)} references extracted",
        elapsed_seconds=round(elapsed, 1),
    ))
    update_stage(session_id, 1)
    return state.model_copy(update={
        "manuscript": manuscript,
        "references": manuscript.references,
        "current_stage": 1,
    })


async def run_extract_claims(
    session_id: str, state: PipelineState,
) -> PipelineState:
    """Run Stage 2: Extract claims (LLM). Gracefully skips on failure."""
    await emit_event(session_id, PipelineEvent(
        stage=2, status="running", message="Extracting claims...",
    ))
    start = time.time()
    try:
        from refcheck.stages.extract_claims import extract_claims

        if not state.manuscript:
            raise ValueError("No manuscript available")

        claims = await extract_claims(state.manuscript)
        elapsed = time.time() - start
        persist_claims(session_id, claims)
        await emit_event(session_id, PipelineEvent(
            stage=2, status="complete",
            message=f"{len(claims)} claims extracted",
            elapsed_seconds=round(elapsed, 1),
        ))
        update_stage(session_id, 2)
        return state.model_copy(update={
            "claims": claims, "current_stage": 2,
        })
    except Exception as exc:
        logger.error("Claim extraction failed: %s", exc)
        await emit_event(session_id, PipelineEvent(
            stage=2, status="error",
            message=f"Claim extraction failed: {exc}",
            elapsed_seconds=round(time.time() - start, 1),
        ))
        update_stage(session_id, 2)
        return state.model_copy(update={"current_stage": 2})


async def run_match(
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

    matched = sum(1 for r in results if r.match_method != "unmatched")
    confirm = sum(1 for r in results if r.needs_user_confirmation)
    updated_refs = apply_matches(state.references, results)
    msg = f"{matched} PDFs matched"
    if confirm:
        msg += f" ({confirm} need confirmation)"

    persist_references(session_id, updated_refs)
    await emit_event(session_id, PipelineEvent(
        stage=3, status="complete", message=msg,
        elapsed_seconds=round(elapsed, 1),
    ))
    update_stage(session_id, 3)
    return state.model_copy(update={
        "match_results": results, "references": updated_refs,
        "current_stage": 3,
    })


async def run_resolve(
    session_id: str, state: PipelineState,
) -> PipelineState:
    """Run Stage 4: Resolve gaps via APIs. V3: Checks library first."""
    from refcheck.services.library import enrich_from_library, populate_library

    await emit_event(session_id, PipelineEvent(
        stage=4, status="running", message="Resolving gaps via APIs...",
    ))
    start = time.time()

    # V3: Check shared library before calling external APIs
    enriched = enrich_from_library(state.references)
    resolved = await resolve_gaps(enriched)
    elapsed = time.time() - start

    # V3: Add newly found PDFs to the shared library
    populate_library(resolved)

    found = sum(1 for r in resolved if r.source_status == "found")
    not_found = sum(1 for r in resolved if r.source_status == "not_found")
    parts = [f"{found} found"]
    if not_found:
        parts.append(f"{not_found} not found")

    persist_references(session_id, resolved)
    await emit_event(session_id, PipelineEvent(
        stage=4, status="complete", message=", ".join(parts),
        elapsed_seconds=round(elapsed, 1),
    ))
    update_stage(session_id, 4)
    return state.model_copy(update={
        "references": resolved, "current_stage": 4,
    })


async def run_verify(
    session_id: str, state: PipelineState,
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

        verifications = await verify_claims(state.claims, state.references)
        elapsed = time.time() - start
        persist_verifications(session_id, verifications)
        await emit_event(session_id, PipelineEvent(
            stage=5, status="complete",
            message=f"{len(verifications)} verifications complete",
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


# run_report is in report_runner.py to stay under 200-line limit
