"""Report download, regeneration, preview, and diff endpoints."""

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlmodel import Session as DBSession

from refcheck.api.routes.report_helpers import (
    build_counts,
    collect_critical,
    collect_minor,
    collect_retracted,
)
from refcheck.db.converters import db_to_claim, db_to_reference, db_to_verification
from refcheck.db.deps import get_db
from refcheck.db.session_repo import get_session as db_get_session
from refcheck.db.session_repo import update_session as db_update_session
from refcheck.models.pipeline import PipelineState
from refcheck.models.reference import ParsedManuscript
from refcheck.stages.generate_report import generate_report as generate_report_fn

router = APIRouter()
logger = logging.getLogger(__name__)


class ReportPreview(BaseModel):
    """JSON preview of report contents."""

    summary: dict[str, int] = Field(default_factory=dict)
    critical_findings: list[dict[str, str]] = Field(default_factory=list)
    minor_issues: list[dict[str, str]] = Field(default_factory=list)
    retracted: list[dict[str, str]] = Field(default_factory=list)
    overrides_count: int = 0
    generated_at: str = ""


class ReportDiff(BaseModel):
    """Diff between original and overridden verification results."""

    changes: list[dict[str, str]] = Field(default_factory=list)
    total_overrides: int = 0


@router.get("/api/sessions/{session_id}/report")
async def download_report(
    session_id: str,
    db: DBSession = Depends(get_db),
) -> FileResponse:
    """Download the generated DOCX report."""
    sess = db_get_session(db, session_id)
    report_path = Path(sess.report_path) if sess and sess.report_path else None
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
async def regenerate_report(
    session_id: str,
    db: DBSession = Depends(get_db),
) -> dict[str, str]:
    """Regenerate the report after user overrides."""
    from refcheck.db.claim_repo import get_claims as db_get_claims
    from refcheck.db.reference_repo import get_all_references
    from refcheck.db.verification_repo import get_all_verifications

    sess = db_get_session(db, session_id)
    if not sess:
        raise HTTPException(404, "Session not found")

    refs = [db_to_reference(r) for r in get_all_references(db, session_id)]
    claims = [db_to_claim(c) for c in db_get_claims(db, session_id)]
    verifications = [
        db_to_verification(v) for v in get_all_verifications(db, session_id)
    ]

    manuscript = ParsedManuscript(filename=sess.manuscript_filename)
    state = PipelineState(
        session_id=session_id, manuscript=manuscript,
        references=refs, claims=claims,
        verification_results=verifications,
    )

    output_path = (
        Path.home() / ".refcheck" / "sessions" / session_id
        / f"refcheck_report_{session_id}.docx"
    )
    await asyncio.to_thread(generate_report_fn, state, output_path)
    db_update_session(db, session_id, report_path=str(output_path))

    now = datetime.now(UTC).isoformat()
    return {"message": "Report regenerated", "generated_at": now}


@router.get("/api/sessions/{session_id}/report/preview")
async def get_report_preview(
    session_id: str,
    db: DBSession = Depends(get_db),
) -> ReportPreview:
    """Get a JSON preview of the report."""
    from refcheck.db.claim_repo import get_claims as db_get_claims
    from refcheck.db.reference_repo import get_all_references
    from refcheck.db.verification_repo import get_all_verifications

    db_vs = get_all_verifications(db, session_id)
    db_refs = get_all_references(db, session_id)
    db_cls = db_get_claims(db, session_id)

    verifications = [db_to_verification(v) for v in db_vs]
    refs = [db_to_reference(r) for r in db_refs]
    claims = [db_to_claim(c) for c in db_cls]
    claims_by_id = {c.id: c for c in claims}

    counts = build_counts(verifications)
    critical = collect_critical(verifications, claims_by_id)
    minor = collect_minor(verifications, claims_by_id)
    retracted = collect_retracted(refs)
    overrides = sum(1 for v in verifications if v.user_override)

    return ReportPreview(
        summary=counts, critical_findings=critical,
        minor_issues=minor, retracted=retracted,
        overrides_count=overrides,
        generated_at=datetime.now(UTC).isoformat(),
    )


@router.get("/api/sessions/{session_id}/report/diff")
async def get_report_diff(
    session_id: str,
    db: DBSession = Depends(get_db),
) -> ReportDiff:
    """Get changes between original and overridden verdicts."""
    from refcheck.db.claim_repo import get_claims as db_get_claims
    from refcheck.db.verification_repo import get_all_verifications

    db_vs = get_all_verifications(db, session_id)
    db_cls = db_get_claims(db, session_id)

    verifications = [db_to_verification(v) for v in db_vs]
    claims = {c.claim_number: db_to_claim(c) for c in db_cls}

    changes: list[dict[str, str]] = []
    for v in verifications:
        if v.user_override:
            claim = claims.get(v.claim_id)
            changes.append({
                "claim_id": str(v.claim_id),
                "claim": claim.extracted_claim if claim else "",
                "original_verdict": v.verdict,
                "new_verdict": v.verdict,
                "reason": v.user_override_reason,
            })

    return ReportDiff(changes=changes, total_overrides=len(changes))
