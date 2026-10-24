"""V5.4 partial-verdict breakdown: partial results per sub-type, guarded results per guard.

Labels, meanings and author actions come from ``models/partial_types.py`` so
the UI and the report describe each type the same way.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlmodel import Session as DBSession

from refcheck.db.converters import db_to_verification
from refcheck.db.deps import get_db
from refcheck.db.verification_repo import get_all_verifications
from refcheck.models.partial_types import GUARD_LABELS, GUARD_ORDER, author_action
from refcheck.models.verification import VerificationResult
from refcheck.stages.generate_report.partial_findings import (
    guarded_results,
    guards_of,
    partial_counts,
    partial_key,
    severity_of,
    type_info,
)

router = APIRouter()


class PartialTypeDetail(BaseModel):
    """Partially supported results of one sub-type."""

    type: str
    label: str
    meaning: str
    severity: str  # the type's default severity
    count: int = 0
    major: int = 0
    minor: int = 0
    author_action: str = ""  # the type's action, without a specific element
    claim_ids: list[int] = Field(default_factory=list)


class GuardDetail(BaseModel):
    """Supported results whose concern one benign guard cleared."""

    guard: str
    label: str
    explanation: str
    count: int = 0
    claim_ids: list[int] = Field(default_factory=list)


class PartialBreakdownResponse(BaseModel):
    """Partial verdicts by type and supported-with-a-note results by guard."""

    total_partial: int = 0
    types: list[PartialTypeDetail] = Field(default_factory=list)
    guarded: int = 0
    guards: list[GuardDetail] = Field(default_factory=list)


def _type_detail(key: str, count: int,
                 verifications: list[VerificationResult]) -> PartialTypeDetail:
    members = [v for v in verifications if partial_key(v) == key]
    label, meaning, severity = type_info(key)
    major = sum(1 for v in members if severity_of(v) == "major")
    return PartialTypeDetail(
        type=key, label=label, meaning=meaning, severity=severity, count=count,
        major=major, minor=count - major, author_action=author_action(key),
        claim_ids=[v.claim_id for v in members],
    )


def build_partial_breakdown(verifications: list[VerificationResult]) -> PartialBreakdownResponse:
    """Breakdown in the report's sub-section order (every type, 0 included)."""
    types = [_type_detail(key, count, verifications)
             for key, count in partial_counts(verifications).items()]
    guarded = guarded_results(verifications)
    guards = [GuardDetail(guard=g, label=GUARD_LABELS[g][0], explanation=GUARD_LABELS[g][1],
                          claim_ids=[v.claim_id for v in guarded if g in guards_of(v)])
              for g in GUARD_ORDER]
    for detail in guards:
        detail.count = len(detail.claim_ids)
    return PartialBreakdownResponse(
        total_partial=sum(t.count for t in types), types=types,
        guarded=len(guarded), guards=guards,
    )


@router.get(
    "/api/sessions/{session_id}/partial-breakdown",
    response_model=PartialBreakdownResponse,
)
async def get_partial_breakdown(
    session_id: str,
    db: DBSession = Depends(get_db),
) -> PartialBreakdownResponse:
    """Partially supported results per sub-type and guarded supported results per guard."""
    verifications = [db_to_verification(v) for v in get_all_verifications(db, session_id)]
    return build_partial_breakdown(verifications)
