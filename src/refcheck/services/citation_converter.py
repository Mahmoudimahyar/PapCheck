"""Convert between VerificationUnit and Claim models."""

from refcheck.models.citation import VerificationUnit
from refcheck.models.claim import Claim
from refcheck.models.evidence import ClaimLocation


def units_to_claims(units: list[VerificationUnit]) -> list[Claim]:
    """Convert VerificationUnits to Claims for backward compatibility."""
    claims: list[Claim] = []
    for unit in units:
        location = ClaimLocation(
            paragraph_index=unit.paragraph_index,
            char_start=unit.char_start,
            char_end=unit.char_end,
            citation_markers=[unit.citation_marker],
            section_heading=unit.section_heading,
        )
        claims.append(Claim(
            id=unit.id,
            manuscript_text=unit.manuscript_text,
            extracted_claim=unit.scope_text,
            claim_type=unit.claim_type,
            reference_ids=[unit.reference_id],
            priority=unit.priority,
            section_heading=unit.section_heading,
            atomic_claims=unit.atomic_claims,
            location=location,
        ))
    return claims
