"""Verification results endpoints (V1)."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session as DBSession

from refcheck.api.routes.results_schemas import (
    ClaimDetail,
    OverrideRequest,
    ResultItem,
    ResultsResponse,
    ResultsSummary,
)
from refcheck.db.converters import db_to_claim, db_to_verification
from refcheck.db.deps import get_db
from refcheck.db.verification_repo import (
    get_all_verifications,
    update_verification,
)
from refcheck.models.claim import Claim
from refcheck.models.verification import VerificationResult

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/sessions/{session_id}/results")
async def get_results(
    session_id: str,
    verdict: str = "all",
    priority: str = "all",
    min_confidence: float = Query(default=0.0, ge=0.0, le=1.0),
    sort: str = "verdict",
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    db: DBSession = Depends(get_db),
) -> ResultsResponse:
    """Get verification results with filtering and pagination."""
    from refcheck.db.claim_repo import get_claims as db_get_claims

    db_verifications = get_all_verifications(db, session_id)
    db_claims = db_get_claims(db, session_id)

    verifications = [db_to_verification(v) for v in db_verifications]
    claims = [db_to_claim(c) for c in db_claims]
    claims_by_id = {c.id: c for c in claims}

    summary = _build_summary(verifications)
    items = _build_items(verifications, claims_by_id)
    items = _apply_filters(items, verdict, priority, min_confidence)
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
            original_v = db_v.verdict
            original_c = db_v.confidence
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
                return _build_items([v], claims_by_id)[0]

    raise HTTPException(404, f"Claim {claim_id} not found")


def _build_summary(verifications: list[VerificationResult]) -> ResultsSummary:
    """Build verdict summary counts."""
    counts: dict[str, int] = {
        "supported": 0, "partially_supported": 0,
        "not_supported": 0, "contradicted": 0, "cannot_verify": 0,
    }
    for v in verifications:
        if v.verdict in counts:
            counts[v.verdict] += 1
    return ResultsSummary(total=len(verifications), **counts)


def _build_items(
    verifications: list[VerificationResult],
    claims_by_id: dict[int, Claim],
) -> list[ResultItem]:
    """Build result items with claim detail."""
    items: list[ResultItem] = []
    for v in verifications:
        claim = claims_by_id.get(v.claim_id)
        claim_detail = ClaimDetail(
            manuscript_text=claim.manuscript_text if claim else "",
            extracted_claim=claim.extracted_claim if claim else "",
            claim_type=claim.claim_type if claim else "",
            priority=claim.priority if claim else "",
        )
        items.append(ResultItem(
            claim_id=v.claim_id, reference_id=v.reference_id,
            verdict=v.verdict, confidence=v.confidence,
            evidence_quotes=v.evidence_quotes, reasoning=v.reasoning,
            tier=v.tier, source_coverage=v.source_coverage,
            needs_user_review=v.needs_user_review,
            user_override=v.user_override,
            user_override_reason=v.user_override_reason,
            claim=claim_detail,
            consensus_type=v.consensus_type,
            final_tier=v.final_tier,
            total_models_consulted=v.total_models_consulted,
            agreement_ratio=v.agreement_ratio,
        ))
    return items


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
    severity = {
        "contradicted": 0, "not_supported": 1,
        "partially_supported": 2, "cannot_verify": 3, "supported": 4,
    }
    return sorted(items, key=lambda i: severity.get(i.verdict, 9))
