"""Report download, regeneration, and preview endpoints."""

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from refcheck.models.claim import Claim
from refcheck.models.pipeline import PipelineState
from refcheck.models.reference import ParsedManuscript, Reference
from refcheck.models.verification import VerificationResult
from refcheck.stages.generate_report import generate_report as generate_report_fn

router = APIRouter()
logger = logging.getLogger(__name__)

_REPORT_PATHS: dict[str, Path] = {}


class ReportPreview(BaseModel):
    """JSON preview of report contents."""

    summary: dict[str, int] = Field(default_factory=dict)
    critical_findings: list[dict[str, str]] = Field(default_factory=list)
    minor_issues: list[dict[str, str]] = Field(default_factory=list)
    retracted: list[dict[str, str]] = Field(default_factory=list)
    overrides_count: int = 0
    generated_at: str = ""


@router.get("/api/sessions/{session_id}/report")
async def download_report(session_id: str) -> FileResponse:
    """Download the generated DOCX report."""
    report_path = _REPORT_PATHS.get(session_id)
    if not report_path or not report_path.exists():
        raise HTTPException(404, "Report not yet generated")

    return FileResponse(
        path=str(report_path),
        media_type=(
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document"
        ),
        filename=f"refcheck_report_{session_id}.docx",
    )


@router.post("/api/sessions/{session_id}/report/regenerate")
async def regenerate_report(session_id: str) -> dict[str, str]:
    """Regenerate the report after user overrides."""
    from refcheck.api.routes.references import get_reference_store
    from refcheck.api.routes.results import (
        get_claims_store,
        get_verification_store,
    )
    from refcheck.api.routes.sessions import get_session_store

    refs = get_reference_store().get(session_id, [])
    claims = get_claims_store().get(session_id, [])
    verifications = get_verification_store().get(session_id, [])
    sessions = get_session_store()

    session = sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    manuscript = ParsedManuscript(filename=session.manuscript_filename)
    state = PipelineState(
        session_id=session_id,
        manuscript=manuscript,
        references=refs,
        claims=claims,
        verification_results=verifications,
    )

    # Determine output path
    old_path = _REPORT_PATHS.get(session_id)
    output_path = old_path or (
        Path.home()
        / ".refcheck"
        / "sessions"
        / session_id
        / f"refcheck_report_{session_id}.docx"
    )

    await asyncio.to_thread(generate_report_fn, state, output_path)
    _REPORT_PATHS[session_id] = output_path

    now = datetime.now(UTC).isoformat()
    return {"message": "Report regenerated", "generated_at": now}


@router.get("/api/sessions/{session_id}/report/preview")
async def get_report_preview(session_id: str) -> ReportPreview:
    """Get a JSON preview of the report."""
    from refcheck.api.routes.references import get_reference_store
    from refcheck.api.routes.results import (
        get_claims_store,
        get_verification_store,
    )

    verifications = get_verification_store().get(session_id, [])
    refs = get_reference_store().get(session_id, [])

    # Build summary counts
    counts: dict[str, int] = {
        "total": len(verifications),
        "supported": 0,
        "partially_supported": 0,
        "not_supported": 0,
        "contradicted": 0,
        "cannot_verify": 0,
    }
    for v in verifications:
        if v.verdict in counts:
            counts[v.verdict] += 1

    # Critical findings (not_supported / contradicted)
    claims = get_claims_store().get(session_id, [])
    claims_by_id = {c.id: c for c in claims}
    critical = _collect_critical(verifications, claims_by_id)

    # Minor issues (partially_supported)
    minor = _collect_minor(verifications, claims_by_id)

    # Retracted references
    retracted = _collect_retracted(refs)

    overrides = sum(1 for v in verifications if v.user_override)
    now = datetime.now(UTC).isoformat()

    return ReportPreview(
        summary=counts,
        critical_findings=critical,
        minor_issues=minor,
        retracted=retracted,
        overrides_count=overrides,
        generated_at=now,
    )


def _collect_critical(
    verifications: list[VerificationResult],
    claims_by_id: dict[int, Claim],
) -> list[dict[str, str]]:
    """Collect critical findings from verifications."""
    critical: list[dict[str, str]] = []
    for v in verifications:
        if v.verdict in ("not_supported", "contradicted"):
            claim = claims_by_id.get(v.claim_id)
            critical.append({
                "claim_id": str(v.claim_id),
                "verdict": v.verdict,
                "claim": claim.extracted_claim if claim else "",
                "reasoning": v.reasoning,
            })
    return critical


def _collect_minor(
    verifications: list[VerificationResult],
    claims_by_id: dict[int, Claim],
) -> list[dict[str, str]]:
    """Collect minor issues from verifications."""
    minor: list[dict[str, str]] = []
    for v in verifications:
        if v.verdict == "partially_supported":
            claim = claims_by_id.get(v.claim_id)
            minor.append({
                "claim_id": str(v.claim_id),
                "verdict": v.verdict,
                "claim": claim.extracted_claim if claim else "",
            })
    return minor


def _collect_retracted(
    refs: list[Reference],
) -> list[dict[str, str]]:
    """Collect retracted references."""
    retracted: list[dict[str, str]] = []
    for r in refs:
        if r.retraction_status not in ("ok", "unknown"):
            retracted.append({
                "ref_id": str(r.id),
                "title": r.title,
                "status": r.retraction_status,
                "detail": r.retraction_detail,
            })
    return retracted


def get_report_store() -> dict[str, Path]:
    """Access report store (for pipeline runner and testing)."""
    return _REPORT_PATHS
