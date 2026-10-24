"""Individual stage runner functions for the pipeline."""

import asyncio
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from refcheck.api.routes.events import emit_event
from refcheck.models.pipeline import PipelineEvent, PipelineState
from refcheck.services.citation_converter import units_to_claims
from refcheck.services.match_applier import apply_matches
from refcheck.services.persist import (
    persist_claims,
    persist_manuscript_sections,
    persist_references,
    update_stage,
)
from refcheck.services.stage_summaries import detect_summary, parse_summary, resolve_summary
from refcheck.stages.detect_citations import detect_all_citations
from refcheck.stages.detect_citations.claim_filter import filter_empty_claims
from refcheck.stages.detect_citations.reference_mapper import (
    map_citations_to_references,
)
from refcheck.stages.detect_citations.scope_resolver import resolve_scopes
from refcheck.stages.match_pdfs import match_pdfs, rematch_or_keep
from refcheck.stages.parse_docx import parse_manuscript
from refcheck.stages.resolve_gaps import resolve_gaps
from refcheck.stages.resolve_gaps.pdf_identity import pdf_identity_status

if TYPE_CHECKING:
    from refcheck.llm.cost_tracker import CostTracker

__all__ = ["resolve_summary", "run_detect_citations", "run_match", "run_parse", "run_resolve"]

logger = logging.getLogger(__name__)


async def run_parse(
    session_id: str, session_dir: Path, state: PipelineState,
    cost_tracker: "CostTracker | None" = None,
) -> PipelineState:
    """Run Stage 1: Parse DOCX (+ title repair via the "utility" role)."""
    await emit_event(session_id, PipelineEvent(
        stage=1, status="running", message="Parsing manuscript...",
    ))
    start = time.time()
    docx_files = list(session_dir.glob("*.docx"))
    if not docx_files:
        raise FileNotFoundError("No DOCX file found in session")

    manuscript = await asyncio.to_thread(parse_manuscript, docx_files[0])

    # Second-pass title repair: heuristics, then one LLM batch (cost-tracked)
    from refcheck.stages.parse_docx.title_llm_repair import repair_reference_titles

    references = await repair_reference_titles(manuscript.references, cost_tracker)
    manuscript = manuscript.model_copy(update={"references": references})
    elapsed = time.time() - start

    for warning in manuscript.warnings:
        logger.warning("Session %s: %s", session_id, warning)
    persist_references(session_id, manuscript.references)
    persist_manuscript_sections(session_id, manuscript.sections)
    await emit_event(session_id, PipelineEvent(
        stage=1, status="complete", message=parse_summary(manuscript),
        elapsed_seconds=round(elapsed, 1),
    ))
    update_stage(session_id, 1)
    return state.model_copy(update={
        "manuscript": manuscript,
        "references": manuscript.references,
        "current_stage": 1,
    })


async def run_detect_citations(
    session_id: str, state: PipelineState,
) -> PipelineState:
    """Run Stage 2: Detect citations (deterministic, no LLM)."""
    await emit_event(session_id, PipelineEvent(
        stage=2, status="running", message="Detecting citations...",
    ))
    start = time.time()
    try:
        if not state.manuscript:
            raise ValueError("No manuscript available")

        citations = detect_all_citations(state.manuscript)
        citations = map_citations_to_references(citations, state.references)
        mapped = [c for c in citations if c.reference_id is not None]
        unmapped = [c for c in citations if c.reference_id is None]
        units = resolve_scopes(mapped)
        claims = filter_empty_claims(units_to_claims(units))

        elapsed = time.time() - start
        persist_claims(session_id, claims)
        await emit_event(session_id, PipelineEvent(
            stage=2, status="complete", message=detect_summary(len(citations), claims),
            elapsed_seconds=round(elapsed, 1),
        ))
        update_stage(session_id, 2)
        return state.model_copy(update={
            "claims": claims,
            "verification_units": units,
            "all_citations": citations,
            "unmapped_citations": unmapped,
            "current_stage": 2,
        })
    except Exception as exc:
        logger.exception("Citation detection failed: %s", exc)
        await emit_event(session_id, PipelineEvent(
            stage=2, status="error",
            message=f"Citation detection failed: {exc}",
            elapsed_seconds=round(time.time() - start, 1),
        ))
        update_stage(session_id, 2)
        raise  # Stage 2 is critical — pipeline cannot continue without claims


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
    # Second chance (DOI printed / title on page 1) before an abstract fallback
    rematch = await asyncio.to_thread(
        rematch_or_keep, state.references, results, pdf_dir, pdf_identity_status)
    results = rematch.results
    elapsed = time.time() - start

    matched = sum(1 for r in results if r.match_method != "unmatched")
    confirm = sum(1 for r in results if r.needs_user_confirmation)
    updated_refs = apply_matches(state.references, results)
    msg = f"{matched} PDFs matched"
    if confirm:
        msg += f" ({confirm} need confirmation)"
    if rematch.records:
        msg += f"; {len(rematch.records)} re-matched by DOI/title"

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
    from refcheck.services.library import enrich_from_library_async, populate_library

    unresolved_count = sum(1 for r in state.references if r.pdf_path is None)
    await emit_event(session_id, PipelineEvent(
        stage=4, status="running", message="Resolving gaps via APIs...",
        progress={"current": 0, "total": float(unresolved_count)},
    ))
    start = time.time()

    # V3: Check shared library before calling external APIs (V5.8: PDF reads and an
    # opted-in open-access fetch run off the event loop)
    enriched = await enrich_from_library_async(state.references)
    resolved = await resolve_gaps(enriched)
    elapsed = time.time() - start

    # V3: Add newly found PDFs to the shared library (never a PDF that
    # failed the identity check — it would poison later sessions)
    await asyncio.to_thread(
        populate_library, [r for r in resolved if r.identity_status != "mismatch"])

    persist_references(session_id, resolved)
    await emit_event(session_id, PipelineEvent(
        stage=4, status="complete", message=resolve_summary(resolved),
        elapsed_seconds=round(elapsed, 1),
    ))
    update_stage(session_id, 4)
    return state.model_copy(update={
        "references": resolved, "current_stage": 4,
    })


# run_verify and run_missing_citations are in verify_runner.py
