"""Verification results endpoints (V1)."""

import logging

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from refcheck.models.claim import Claim
from refcheck.models.verification import VerificationResult

router = APIRouter()
logger = logging.getLogger(__name__)

# In-memory stores populated by pipeline_runner
_CLAIMS_STORE: dict[str, list[Claim]] = {}
_VERIFICATION_STORE: dict[str, list[VerificationResult]] = {}


class ResultsSummary(BaseModel):
    """Summary of verification results."""

    total: int = 0
    supported: int = 0
    partially_supported: int = 0
    not_supported: int = 0
    contradicted: int = 0
    cannot_verify: int = 0


class ClaimDetail(BaseModel):
    """Claim info included in results response."""

    manuscript_text: str = ""
    extracted_claim: str = ""
    claim_type: str = ""
    priority: str = ""


class ResultItem(BaseModel):
    """Single result in the results response."""

    claim_id: int
    reference_id: int
    verdict: str
    confidence: float
    evidence_quotes: list[str] = Field(default_factory=list)
    reasoning: str = ""
    tier: int = 1
    source_coverage: str = "no_source"
    needs_user_review: bool = False
    claim: ClaimDetail = Field(default_factory=ClaimDetail)


class ResultsResponse(BaseModel):
    """Full paginated results response."""

    summary: ResultsSummary
    results: list[ResultItem]
    total: int
    page: int
    per_page: int


@router.get("/api/sessions/{session_id}/results")
async def get_results(
    session_id: str,
    verdict: str = "all",
    priority: str = "all",
    min_confidence: float = Query(default=0.0, ge=0.0, le=1.0),
    sort: str = "verdict",
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
) -> ResultsResponse:
    """Get verification results with filtering and pagination."""
    verifications = _VERIFICATION_STORE.get(session_id, [])
    claims = _CLAIMS_STORE.get(session_id, [])
    claims_by_id = {c.id: c for c in claims}

    # Build summary from unfiltered results
    summary = _build_summary(verifications)

    # Build result items
    items = _build_items(verifications, claims_by_id)

    # Apply filters
    items = _apply_filters(items, verdict, priority, min_confidence)

    # Sort
    items = _sort_items(items, sort)

    # Paginate
    total = len(items)
    start = (page - 1) * per_page
    end = start + per_page
    page_items = items[start:end]

    return ResultsResponse(
        summary=summary,
        results=page_items,
        total=total,
        page=page,
        per_page=per_page,
    )


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
            claim_id=v.claim_id,
            reference_id=v.reference_id,
            verdict=v.verdict,
            confidence=v.confidence,
            evidence_quotes=v.evidence_quotes,
            reasoning=v.reasoning,
            tier=v.tier,
            source_coverage=v.source_coverage,
            needs_user_review=v.needs_user_review,
            claim=claim_detail,
        ))
    return items


def _apply_filters(
    items: list[ResultItem],
    verdict: str,
    priority: str,
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
    # Default: sort by verdict severity
    severity = {
        "contradicted": 0, "not_supported": 1,
        "partially_supported": 2, "cannot_verify": 3, "supported": 4,
    }
    return sorted(items, key=lambda i: severity.get(i.verdict, 9))


def get_claims_store() -> dict[str, list[Claim]]:
    """Access claims store (for pipeline runner)."""
    return _CLAIMS_STORE


def get_verification_store() -> dict[str, list[VerificationResult]]:
    """Access verification store (for pipeline runner)."""
    return _VERIFICATION_STORE
