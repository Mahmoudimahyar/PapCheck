"""Claims management endpoints (V2)."""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from refcheck.api.routes.results import get_claims_store
from refcheck.models.claim import Claim

router = APIRouter()
logger = logging.getLogger(__name__)


class ClaimUpdateRequest(BaseModel):
    """Request body for updating a claim."""

    extracted_claim: str | None = None
    claim_type: str | None = None
    priority: str | None = None


@router.get("/api/sessions/{session_id}/claims")
async def list_claims(session_id: str) -> list[Claim]:
    """List all claims for a session."""
    claims = get_claims_store().get(session_id, [])
    return claims


@router.put("/api/sessions/{session_id}/claims/{claim_id}")
async def update_claim(
    session_id: str,
    claim_id: int,
    body: ClaimUpdateRequest,
) -> Claim:
    """Update a claim's text, type, or priority."""
    claims = get_claims_store().get(session_id)
    if claims is None:
        raise HTTPException(404, f"Session {session_id} not found")

    for i, c in enumerate(claims):
        if c.id == claim_id:
            updates: dict[str, object] = {}
            if body.extracted_claim is not None:
                updates["extracted_claim"] = body.extracted_claim
            if body.claim_type is not None:
                updates["claim_type"] = body.claim_type
            if body.priority is not None:
                updates["priority"] = body.priority
            claims[i] = c.model_copy(update=updates)
            return claims[i]

    raise HTTPException(404, f"Claim {claim_id} not found")


@router.delete("/api/sessions/{session_id}/claims/{claim_id}")
async def delete_claim(
    session_id: str,
    claim_id: int,
) -> dict[str, str]:
    """Delete a claim from the session."""
    claims = get_claims_store().get(session_id)
    if claims is None:
        raise HTTPException(404, f"Session {session_id} not found")

    for i, c in enumerate(claims):
        if c.id == claim_id:
            claims.pop(i)
            return {"message": f"Claim {claim_id} deleted"}

    raise HTTPException(404, f"Claim {claim_id} not found")
