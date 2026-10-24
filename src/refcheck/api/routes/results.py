"""Verification results endpoints (V1; V5 adds the cascade trace)."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session as DBSession

from refcheck.api.routes.results_builders import build_items, build_summary
from refcheck.api.routes.results_schemas import (
    OverrideRequest,
    ResultItem,
    ResultsResponse,
)
from refcheck.api.routes.sessions import session_dir_of
from refcheck.db.converters import db_to_claim, db_to_verification
from refcheck.db.deps import get_db
from refcheck.db.verification_repo import (
    get_all_verifications,
    update_verification,
)
from refcheck.stages.generate_report.partial_findings import matches_partial_filter

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/sessions/{session_id}/results")
async def get_results(
    session_id: str,
    verdict: str = "all",
    priority: str = "all",
    min_confidence: float = Query(default=0.0, ge=0.0, le=1.0),
    sort: str = "verdict",
    partial_type: str = "all",
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    db: DBSession = Depends(get_db),
) -> ResultsResponse:
    """Get verification results with filtering and pagination.

    ``partial_type``: a sub-type id (partially supported results of that type,
    "unclassified" for legacy rows), "guarded" (supported results a benign guard
    cleared) or "guarded:<guard>"; combined with the other filters (AND).
    """
    from refcheck.db.claim_repo import get_claims as db_get_claims

    db_verifications = get_all_verifications(db, session_id)
    db_claims = db_get_claims(db, session_id)

    verifications = [db_to_verification(v) for v in db_verifications]
    claims = [db_to_claim(c) for c in db_claims]
    claims_by_id = {c.id: c for c in claims}

    summary = build_summary(verifications, session_dir_of(session_id))
    items = build_items(verifications, claims_by_id)
    items = _apply_filters(items, verdict, priority, min_confidence)
    if partial_type != "all":
        items = [i for i in items if matches_partial_filter(
            i.verdict, i.partial_type, i.guards_applied, partial_type)]
    items = _sort_items(items, sort)

    total = len(items)
    start = (page - 1) * per_page
    end = start + per_page

    return ResultsResponse(
        summary=summary, results=items[start:end],
        total=total, page=page, per_page=per_page,
    )


@router.post("/api/sessions/{session_id}/results/{claim_id}/override")
async def override_verdict(
    session_id: str,
    claim_id: int,
    body: OverrideRequest,
    db: DBSession = Depends(get_db),
) -> ResultItem:
    """Override a verification verdict for a specific claim."""
    from refcheck.db.claim_repo import get_claims as db_get_claims

    db_verifications = get_all_verifications(db, session_id)
    if not db_verifications:
        raise HTTPException(404, f"Session {session_id} not found")

    db_claims = db_get_claims(db, session_id)
    claims = [db_to_claim(c) for c in db_claims]
    claims_by_id = {c.id: c for c in claims}

    for db_v in db_verifications:
        if db_v.claim_id == claim_id:
            # A second override keeps the model's verdict as the original one.
            reviewed = bool(db_v.user_override and db_v.original_verdict)
            original_v = db_v.original_verdict if reviewed else db_v.verdict
            original_c = db_v.original_confidence if reviewed else db_v.confidence
            updated = update_verification(
                db, session_id, claim_id,
                verdict=body.verdict,
                user_override=True,
                user_override_reason=body.reason,
                needs_user_review=False,
                original_verdict=original_v,
                original_confidence=original_c,
            )
            if updated:
                v = db_to_verification(updated)
                return build_items([v], claims_by_id)[0]

    raise HTTPException(404, f"Claim {claim_id} not found")


def _apply_filters(
    items: list[ResultItem], verdict: str, priority: str,
    min_confidence: float,
) -> list[ResultItem]:
    """Apply verdict, priority, and confidence filters."""
    if verdict != "all":
        items = [i for i in items if i.verdict == verdict]
    if priority != "all":
        items = [i for i in items if i.claim.priority == priority]
    if min_confidence > 0:
        items = [i for i in items if i.confidence >= min_confidence]
    return items


def _sort_items(items: list[ResultItem], sort: str) -> list[ResultItem]:
    """Sort result items."""
    if sort == "confidence":
        return sorted(items, key=lambda i: i.confidence, reverse=True)
    if sort == "priority":
        order = {"high": 0, "medium": 1, "low": 2}
        return sorted(items, key=lambda i: order.get(i.claim.priority, 9))
    if sort == "ref_id":
        return sorted(items, key=lambda i: i.reference_id)
    if sort == "risk":  # V5: fast-screen P(problem), highest first; unscreened last
        return sorted(items, key=lambda i: -1.0 if i.screen_p_problem is None
                      else i.screen_p_problem, reverse=True)
    severity = {
        "contradicted": 0, "not_supported": 1, "not_relevant": 2,
        "partially_supported": 3, "cannot_verify": 4, "supported": 5,
    }
    return sorted(items, key=lambda i: severity.get(i.verdict, 9))
