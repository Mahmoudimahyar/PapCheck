"""Cannot-verify breakdown (V2), bibliography / source issues (V5.2) and partial-type
breakdown (V5.4, routes in partial_breakdown.py) endpoints."""

import logging
from collections import defaultdict

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlmodel import Session as DBSession

from refcheck.api.routes.partial_breakdown import router as partial_router
from refcheck.db.claim_repo import get_claims
from refcheck.db.converters import db_to_claim, db_to_reference, db_to_verification
from refcheck.db.deps import get_db
from refcheck.db.reference_repo import get_all_references
from refcheck.db.verification_repo import get_all_verifications
from refcheck.stages.generate_report.source_issues import (
    ISSUE_LABELS,
    SourceIssue,
    collect_source_issues,
)

router = APIRouter()
router.include_router(partial_router)
logger = logging.getLogger(__name__)


class ReasonDetail(BaseModel):
    """Count and claim IDs for a single cannot-verify reason."""

    count: int = 0
    claim_ids: list[int] = Field(default_factory=list)


class BreakdownResponse(BaseModel):
    """Cannot-verify breakdown response."""

    total: int = 0
    reasons: dict[str, ReasonDetail] = Field(default_factory=dict)


def _issue_labels() -> dict[str, str]:
    return {str(kind): label for kind, label in ISSUE_LABELS.items()}


class SourceIssuesResponse(BaseModel):
    """Problems with the reference list and the attached PDFs."""

    issues: list[SourceIssue] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=_issue_labels)


@router.get(
    "/api/sessions/{session_id}/cannot-verify-breakdown",
    response_model=BreakdownResponse,
)
async def get_cannot_verify_breakdown(
    session_id: str,
    db: DBSession = Depends(get_db),
) -> BreakdownResponse:
    """Get breakdown of cannot-verify reasons with claim IDs."""
    db_verifications = get_all_verifications(db, session_id)
    verifications = [db_to_verification(v) for v in db_verifications]

    reasons: dict[str, list[int]] = defaultdict(list)
    total = 0

    for v in verifications:
        if v.verdict != "cannot_verify":
            continue
        total += 1
        reason = v.cannot_verify_reason or "unknown"
        reasons[reason].append(v.claim_id)

    reason_details = {
        k: ReasonDetail(count=len(ids), claim_ids=ids)
        for k, ids in reasons.items()
    }

    return BreakdownResponse(total=total, reasons=reason_details)


@router.get(
    "/api/sessions/{session_id}/source-issues",
    response_model=SourceIssuesResponse,
)
async def get_source_issues(
    session_id: str,
    db: DBSession = Depends(get_db),
) -> SourceIssuesResponse:
    """Duplicates, ambiguous citations, wrong / scanned / supplement PDFs, repaired titles."""
    refs = [db_to_reference(r) for r in get_all_references(db, session_id)]
    claims = [db_to_claim(c) for c in get_claims(db, session_id)]
    verifications = [db_to_verification(v) for v in get_all_verifications(db, session_id)]
    return SourceIssuesResponse(issues=collect_source_issues(refs, claims, verifications))
