"""Convert between Pydantic domain models and SQLModel DB models."""

import json
from pathlib import Path

from refcheck.db.event_converters import (
    db_to_event,
    db_to_session,
    event_to_db,
    session_to_db,
)
from refcheck.db.models import ClaimDB, ReferenceDB, VerificationDB
from refcheck.models.claim import Claim
from refcheck.models.evidence import ClaimLocation, EvidenceSection
from refcheck.models.reference import Reference
from refcheck.models.verification import AtomicVerification, VerificationResult

__all__ = [
    "claim_to_db",
    "db_to_claim",
    "db_to_event",
    "db_to_reference",
    "db_to_session",
    "db_to_verification",
    "event_to_db",
    "reference_to_db",
    "session_to_db",
    "verification_to_db",
]


def reference_to_db(ref: Reference, session_id: str) -> ReferenceDB:
    """Convert a Pydantic Reference to a ReferenceDB row."""
    return ReferenceDB(
        session_id=session_id,
        ref_number=ref.id,
        raw_text=ref.raw_text,
        title=ref.title,
        authors_json=json.dumps(ref.authors),
        year=ref.year,
        doi=ref.doi,
        journal=ref.journal,
        pmid=ref.pmid,
        volume=ref.volume,
        pages=ref.pages,
        url=ref.url,
        source_status=ref.source_status,
        pdf_path=str(ref.pdf_path) if ref.pdf_path else None,
        pdf_source=ref.pdf_source,
        journal_url=ref.journal_url,
        retraction_status=ref.retraction_status,
        retraction_detail=ref.retraction_detail,
        duplicate_of=ref.duplicate_of,
        is_supplementary=ref.is_supplementary,
    )


def db_to_reference(db_ref: ReferenceDB) -> Reference:
    """Convert a ReferenceDB row to a Pydantic Reference."""
    return Reference(
        id=db_ref.ref_number,
        raw_text=db_ref.raw_text,
        title=db_ref.title,
        authors=json.loads(db_ref.authors_json),
        year=db_ref.year,
        doi=db_ref.doi,
        journal=db_ref.journal,
        pmid=db_ref.pmid,
        volume=db_ref.volume,
        pages=db_ref.pages,
        url=db_ref.url,
        source_status=db_ref.source_status,  # type: ignore[arg-type]
        pdf_path=Path(db_ref.pdf_path) if db_ref.pdf_path else None,
        pdf_source=db_ref.pdf_source,  # type: ignore[arg-type]
        journal_url=db_ref.journal_url,
        retraction_status=db_ref.retraction_status,  # type: ignore[arg-type]
        retraction_detail=db_ref.retraction_detail,
        duplicate_of=db_ref.duplicate_of,
        is_supplementary=db_ref.is_supplementary,
    )


def claim_to_db(claim: Claim, session_id: str) -> ClaimDB:
    """Convert a Pydantic Claim to a ClaimDB row."""
    location_json = None
    if claim.location is not None:
        location_json = claim.location.model_dump_json()
    return ClaimDB(
        session_id=session_id,
        claim_number=claim.id,
        manuscript_text=claim.manuscript_text,
        extracted_claim=claim.extracted_claim,
        claim_type=claim.claim_type,
        reference_ids_json=json.dumps(claim.reference_ids),
        priority=claim.priority,
        section_heading=claim.section_heading,
        atomic_claims_json=json.dumps(claim.atomic_claims),
        location_json=location_json,
    )


def db_to_claim(db_claim: ClaimDB) -> Claim:
    """Convert a ClaimDB row to a Pydantic Claim."""
    location = None
    if db_claim.location_json:
        location = ClaimLocation.model_validate_json(db_claim.location_json)
    return Claim(
        id=db_claim.claim_number,
        manuscript_text=db_claim.manuscript_text,
        extracted_claim=db_claim.extracted_claim,
        claim_type=db_claim.claim_type,  # type: ignore[arg-type]
        reference_ids=json.loads(db_claim.reference_ids_json),
        priority=db_claim.priority,  # type: ignore[arg-type]
        section_heading=db_claim.section_heading,
        atomic_claims=json.loads(db_claim.atomic_claims_json),
        location=location,
    )


def verification_to_db(v: VerificationResult, session_id: str) -> VerificationDB:
    """Convert a Pydantic VerificationResult to a VerificationDB row."""
    atomic_json = None
    if v.atomic_results is not None:
        atomic_json = json.dumps([a.model_dump() for a in v.atomic_results])
    evidence_sections_json = None
    if v.evidence_sections:
        evidence_sections_json = json.dumps(
            [s.model_dump() for s in v.evidence_sections]
        )

    return VerificationDB(
        session_id=session_id,
        claim_id=v.claim_id,
        reference_id=v.reference_id,
        verdict=v.verdict,
        confidence=v.confidence,
        evidence_quotes_json=json.dumps(v.evidence_quotes),
        reasoning=v.reasoning,
        tier=v.tier,
        source_coverage=v.source_coverage,
        needs_user_review=v.needs_user_review,
        user_override=v.user_override,
        user_override_reason=v.user_override_reason,
        original_verdict=v.original_verdict,
        original_confidence=v.original_confidence,
        atomic_results_json=atomic_json,
        evidence_sections_json=evidence_sections_json,
    )


def db_to_verification(db_v: VerificationDB) -> VerificationResult:
    """Convert a VerificationDB row to a Pydantic VerificationResult."""
    atomic_results = None
    if db_v.atomic_results_json:
        raw = json.loads(db_v.atomic_results_json)
        atomic_results = [AtomicVerification(**a) for a in raw]
    evidence_sections: list[EvidenceSection] = []
    if db_v.evidence_sections_json:
        raw_sections = json.loads(db_v.evidence_sections_json)
        evidence_sections = [EvidenceSection(**s) for s in raw_sections]

    return VerificationResult(
        claim_id=db_v.claim_id,
        reference_id=db_v.reference_id,
        verdict=db_v.verdict,  # type: ignore[arg-type]
        confidence=db_v.confidence,
        evidence_quotes=json.loads(db_v.evidence_quotes_json),
        reasoning=db_v.reasoning,
        tier=db_v.tier,  # type: ignore[arg-type]
        source_coverage=db_v.source_coverage,  # type: ignore[arg-type]
        needs_user_review=db_v.needs_user_review,
        user_override=db_v.user_override,
        user_override_reason=db_v.user_override_reason,
        original_verdict=db_v.original_verdict,  # type: ignore[arg-type]
        original_confidence=db_v.original_confidence,
        atomic_results=atomic_results,
        evidence_sections=evidence_sections,
    )


