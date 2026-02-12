"""Parse and validate LLM claim extraction responses."""

import logging
from typing import Literal

from pydantic import BaseModel, Field

from refcheck.models.claim import Claim

logger = logging.getLogger(__name__)

# Priority mapping by claim type
_PRIORITY_MAP: dict[str, Literal["high", "medium", "low"]] = {
    "factual": "high",
    "contrast": "high",
    "methodological": "medium",
    "background": "low",
    "attribution": "low",
    "interpretive": "low",
}


class ClaimExtractionResponse(BaseModel):
    """LLM response shape for claim extraction."""

    claims: list[Claim] = Field(default_factory=list)


class AtomicDecompositionResponse(BaseModel):
    """LLM response shape for atomic claim decomposition (V2)."""

    atoms: list[str] = Field(default_factory=list)


def apply_priority(claim: Claim) -> Claim:
    """Enforce priority mapping based on claim type."""
    correct_priority = _PRIORITY_MAP.get(claim.claim_type, "medium")
    if claim.priority != correct_priority:
        return claim.model_copy(update={"priority": correct_priority})
    return claim


def filter_invalid_refs(
    claims: list[Claim],
    valid_ref_ids: set[int],
) -> list[Claim]:
    """Remove claims referencing non-existent reference IDs."""
    filtered: list[Claim] = []
    for claim in claims:
        valid_ids = [rid for rid in claim.reference_ids if rid in valid_ref_ids]
        if not valid_ids:
            logger.warning(
                "Claim '%s' has no valid reference IDs, skipping",
                claim.extracted_claim[:50],
            )
            continue
        if len(valid_ids) != len(claim.reference_ids):
            logger.warning(
                "Claim '%s' had invalid ref IDs removed: %s",
                claim.extracted_claim[:50],
                set(claim.reference_ids) - set(valid_ids),
            )
        filtered.append(claim.model_copy(update={"reference_ids": valid_ids}))
    return filtered


def deduplicate_claims(claims: list[Claim]) -> list[Claim]:
    """Merge duplicate claims (same text and same references)."""
    seen: dict[str, Claim] = {}
    for claim in claims:
        key = f"{claim.extracted_claim.lower().strip()}|{sorted(claim.reference_ids)}"
        if key not in seen:
            seen[key] = claim
    return list(seen.values())


def assign_sequential_ids(claims: list[Claim], start_id: int = 1) -> list[Claim]:
    """Assign sequential IDs to claims starting from start_id."""
    return [
        claim.model_copy(update={"id": start_id + i})
        for i, claim in enumerate(claims)
    ]
