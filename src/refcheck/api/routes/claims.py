"""Claims management endpoints (V2)."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session as DBSession

from refcheck.db.claim_repo import (
    delete_claim as db_delete_claim,
)
from refcheck.db.claim_repo import (
    get_claims as db_get_claims,
)
from refcheck.db.claim_repo import (
    update_claim as db_update_claim,
)
from refcheck.db.converters import db_to_claim
from refcheck.db.deps import get_db
from refcheck.models.claim import Claim

router = APIRouter()
logger = logging.getLogger(__name__)


class ClaimUpdateRequest(BaseModel):
    """Request body for updating a claim."""

    extracted_claim: str | None = None
    claim_type: str | None = None
    priority: str | None = None


@router.get("/api/sessions/{session_id}/claims")
async def list_claims(
    session_id: str,
    db: DBSession = Depends(get_db),
) -> list[Claim]:
    """List all claims for a session."""
    db_claims = db_get_claims(db, session_id)
    return [db_to_claim(c) for c in db_claims]


@router.put("/api/sessions/{session_id}/claims/{claim_id}")
async def update_claim(
    session_id: str,
    claim_id: int,
    body: ClaimUpdateRequest,
    db: DBSession = Depends(get_db),
) -> Claim:
    """Update a claim's text, type, or priority."""
    updates: dict[str, object] = {}
    if body.extracted_claim is not None:
        updates["extracted_claim"] = body.extracted_claim
    if body.claim_type is not None:
        updates["claim_type"] = body.claim_type
    if body.priority is not None:
        updates["priority"] = body.priority

    if not updates:
        raise HTTPException(400, "No fields to update")

    result = db_update_claim(db, session_id, claim_id, **updates)
    if not result:
        raise HTTPException(404, f"Claim {claim_id} not found")
    return db_to_claim(result)


@router.delete("/api/sessions/{session_id}/claims/{claim_id}")
async def delete_claim(
    session_id: str,
    claim_id: int,
    db: DBSession = Depends(get_db),
) -> dict[str, str]:
    """Delete a claim from the session."""
    deleted = db_delete_claim(db, session_id, claim_id)
    if not deleted:
        raise HTTPException(404, f"Claim {claim_id} not found")
    return {"message": f"Claim {claim_id} deleted"}
