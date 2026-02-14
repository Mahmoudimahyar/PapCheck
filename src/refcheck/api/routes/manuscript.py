"""Manuscript viewer API endpoints (V2)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException

from refcheck.api.routes.manuscript_helpers import (
    attach_claims_to_paragraphs,
    best_verdict,
    build_paragraphs_from_sections,
    build_verification_evidences,
    group_verifications,
)
from refcheck.api.routes.manuscript_schemas import (
    ClaimDetailResponse,
    EvidenceResponse,
    ManuscriptParagraph,
    ManuscriptResponse,
)
from refcheck.db.claim_repo import get_claims as db_get_claims
from refcheck.db.converters import db_to_claim, db_to_reference, db_to_verification
from refcheck.db.deps import get_db
from refcheck.db.reference_repo import get_all_references
from refcheck.db.session_repo import get_session
from refcheck.db.verification_repo import get_all_verifications

if TYPE_CHECKING:
    from sqlmodel import Session as DBSession

    from refcheck.models.claim import Claim
    from refcheck.models.reference import Reference
    from refcheck.models.verification import VerificationResult

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/sessions/{session_id}/manuscript")
async def get_manuscript(
    session_id: str,
    db: DBSession = Depends(get_db),
) -> ManuscriptResponse:
    """Get the full manuscript structured for the viewer."""
    claims, verifications = _load_data(db, session_id)
    paragraphs = _load_paragraphs(db, session_id)

    v_by_claim = group_verifications(verifications)
    legend: dict[str, int] = {}
    unmapped: list[int] = []

    for claim in claims:
        verdict = best_verdict(claim.id, v_by_claim)
        legend[verdict] = legend.get(verdict, 0) + 1
        if claim.location is None:
            unmapped.append(claim.id)

    attach_claims_to_paragraphs(paragraphs, claims, v_by_claim)

    return ManuscriptResponse(
        title="",
        paragraphs=paragraphs,
        legend=legend,
        total_claims=len(claims),
        total_paragraphs=len(paragraphs),
        unmapped_claims=unmapped,
    )


@router.get("/api/sessions/{session_id}/evidence/{claim_id}")
async def get_evidence(
    session_id: str,
    claim_id: int,
    db: DBSession = Depends(get_db),
) -> EvidenceResponse:
    """Get full evidence for a specific claim."""
    claims, verifications = _load_data(db, session_id)
    claim = next((c for c in claims if c.id == claim_id), None)
    if not claim:
        raise HTTPException(404, f"Claim {claim_id} not found")

    db_refs = get_all_references(db, session_id)
    refs_by_id: dict[int, Reference] = {
        db_to_reference(r).id: db_to_reference(r) for r in db_refs
    }

    claim_vs = [v for v in verifications if v.claim_id == claim_id]
    ev_list = build_verification_evidences(claim_vs, refs_by_id)

    return EvidenceResponse(
        claim=ClaimDetailResponse(
            id=claim.id,
            manuscript_text=claim.manuscript_text,
            extracted_claim=claim.extracted_claim,
            claim_type=claim.claim_type,
            priority=claim.priority,
            atomic_claims=claim.atomic_claims,
            location=claim.location,
        ),
        verifications=ev_list,
    )


def _load_data(
    db: DBSession, session_id: str,
) -> tuple[list[Claim], list[VerificationResult]]:
    """Load claims and verifications from DB."""
    db_claims = db_get_claims(db, session_id)
    db_vs = get_all_verifications(db, session_id)
    claims = [db_to_claim(c) for c in db_claims]
    verifications = [db_to_verification(v) for v in db_vs]
    return claims, verifications


def _load_paragraphs(
    db: DBSession, session_id: str,
) -> list[ManuscriptParagraph]:
    """Build paragraph list from stored manuscript sections."""
    import json

    from refcheck.models.reference import ManuscriptSection

    sess = get_session(db, session_id)
    if not sess or not sess.manuscript_sections_json:
        return []
    raw = json.loads(sess.manuscript_sections_json)
    sections = [ManuscriptSection(**s) for s in raw]
    return build_paragraphs_from_sections(sections)
