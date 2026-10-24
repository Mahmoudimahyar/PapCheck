"""Convert between Pydantic domain models and SQLModel DB models.

Readers coalesce NULLs from columns added by later migrations so rows
written by older versions still load (see ``or_default``).
"""

import json
from pathlib import Path
from typing import Literal

from refcheck.db.event_converters import (
    db_to_event,
    db_to_session,
    event_to_db,
    session_to_db,
)
from refcheck.db.models import ClaimDB, ReferenceDB
from refcheck.db.verification_converters import (
    db_to_verification,
    load_json_list,
    or_default,
    verification_to_db,
)
from refcheck.models.claim import Claim, ClaimQuality
from refcheck.models.evidence import ClaimLocation
from refcheck.models.open_access import (
    OA_FIELDS,
    OpenAccessHint,
    ReferenceWithAccess,
    access_hint_of,
    with_access_hint,
)
from refcheck.models.reference import Reference

__all__ = [
    "claim_to_db",
    "db_to_claim",
    "db_to_event",
    "db_to_reference",
    "db_to_reference_with_access",
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
        pmc_id=ref.pmc_id,
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
        raw_text_original=ref.raw_text_original,
        repair_applied=ref.repair_applied,
        reference_type=ref.reference_type,
        abstract_text=ref.abstract_text,
        abstract_source=ref.abstract_source,
        identity_status=ref.identity_status,
        year_suffix=ref.year_suffix,
        replaced_upload_reason=ref.replaced_upload_reason,
        **access_hint_of(ref).model_dump(include=set(OA_FIELDS)),
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
        pmc_id=db_ref.pmc_id,
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
        raw_text_original=or_default(db_ref.raw_text_original, ""),
        repair_applied=or_default(db_ref.repair_applied, "none"),
        reference_type=or_default(db_ref.reference_type, "journal_article"),
        abstract_text=db_ref.abstract_text,
        abstract_source=db_ref.abstract_source,
        identity_status=_identity_status(db_ref.identity_status),
        year_suffix=db_ref.year_suffix or None,
        replaced_upload_reason=db_ref.replaced_upload_reason or None,
    )


def db_to_reference_with_access(db_ref: ReferenceDB) -> ReferenceWithAccess:
    """A ReferenceDB row with its free-full-text hint (references API)."""
    hint = OpenAccessHint(**{name: getattr(db_ref, name, None) for name in OA_FIELDS})
    return with_access_hint(db_to_reference(db_ref), hint)


def _identity_status(raw: str | None) -> Literal["verified", "unverified", "mismatch"]:
    if raw == "verified":
        return "verified"
    if raw == "mismatch":
        return "mismatch"
    return "unverified"  # also NULL rows written before the V5 migration


def claim_to_db(claim: Claim, session_id: str) -> ClaimDB:
    """Convert a Pydantic Claim to a ClaimDB row."""
    location_json = None
    if claim.location is not None:
        location_json = claim.location.model_dump_json()
    return ClaimDB(
        session_id=session_id,
        claim_number=claim.id,
        manuscript_text=claim.manuscript_text,
        paragraph_text=claim.paragraph_text,
        extracted_claim=claim.extracted_claim,
        claim_type=claim.claim_type,
        reference_ids_json=json.dumps(claim.reference_ids),
        priority=claim.priority,
        section_heading=claim.section_heading,
        atomic_claims_json=json.dumps(claim.atomic_claims),
        location_json=location_json,
        co_cited_count=claim.co_cited_count,
        cited_for=claim.cited_for,
        claim_quality=claim.claim_quality,
        mapping_ambiguous=claim.mapping_ambiguous,
        candidate_reference_ids_json=json.dumps(claim.candidate_reference_ids),
    )


def db_to_claim(db_claim: ClaimDB) -> Claim:
    """Convert a ClaimDB row to a Pydantic Claim."""
    location = None
    if db_claim.location_json:
        location = ClaimLocation.model_validate_json(db_claim.location_json)
    return Claim(
        id=db_claim.claim_number,
        manuscript_text=db_claim.manuscript_text,
        paragraph_text=or_default(db_claim.paragraph_text, ""),
        extracted_claim=db_claim.extracted_claim,
        claim_type=db_claim.claim_type,  # type: ignore[arg-type]
        reference_ids=json.loads(db_claim.reference_ids_json),
        priority=db_claim.priority,  # type: ignore[arg-type]
        section_heading=db_claim.section_heading,
        atomic_claims=json.loads(db_claim.atomic_claims_json),
        location=location,
        co_cited_count=max(1, or_default(db_claim.co_cited_count, 1)),
        cited_for=or_default(db_claim.cited_for, ""),
        claim_quality=_claim_quality(db_claim.claim_quality),
        mapping_ambiguous=bool(db_claim.mapping_ambiguous),
        candidate_reference_ids=[
            i for i in load_json_list(db_claim.candidate_reference_ids_json,
                                      "candidate_reference_ids_json")
            if isinstance(i, int)
        ],
    )


def _claim_quality(raw: str | None) -> ClaimQuality:
    return "fragment" if raw == "fragment" else "ok"  # NULL rows predate V5.2
