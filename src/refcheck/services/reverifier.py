"""Re-verification after a user uploads a PDF for one reference.

The upload changes the source document, so every claim citing that
reference is re-verified, except claims whose verdict the user set by hand.
Results are merged into the session's stored verifications. A metadata refresh
(new abstract) re-verifies the same way.
"""

import asyncio
import logging
from pathlib import Path

from pydantic import BaseModel, Field
from sqlmodel import Session as DBSession

from refcheck.db.converters import (
    db_to_claim,
    db_to_reference,
    db_to_reference_with_access,
    db_to_verification,
)
from refcheck.db.engine import get_db_session
from refcheck.db.reference_repo import get_reference, update_reference
from refcheck.db.verification_repo import get_all_verifications
from refcheck.models.claim import Claim
from refcheck.models.open_access import OpenAccessHint
from refcheck.models.reference import Reference
from refcheck.models.verification import VerificationResult
from refcheck.services.persist import persist_verifications

logger = logging.getLogger(__name__)

SESSIONS_DIR = Path.home() / ".refcheck" / "sessions"
_SESSION_LOCKS: dict[str, asyncio.Lock] = {}


def find_claims_to_reverify(
    claims: list[Claim],
    verification_results: list[VerificationResult],
    reference_id: int,
) -> list[int]:
    """IDs of claims citing the reference, minus user-overridden verdicts."""
    overridden = {
        v.claim_id for v in verification_results
        if v.reference_id == reference_id and v.user_override
    }
    return [
        c.id for c in claims
        if reference_id in c.reference_ids and c.id not in overridden
    ]


def save_uploaded_pdf(pdf_dir: Path, reference_id: int, content: bytes) -> Path:
    """Write the uploaded PDF into the session PDF directory."""
    pdf_dir.mkdir(parents=True, exist_ok=True)
    path = pdf_dir / f"ref_{reference_id}_user_upload.pdf"
    path.write_bytes(content)
    return path


def merge_verifications(
    existing: list[VerificationResult], new: list[VerificationResult],
) -> list[VerificationResult]:
    """Replace stored results for the re-verified (claim, reference) pairs."""
    replaced = {(v.claim_id, v.reference_id) for v in new}
    kept = [v for v in existing if (v.claim_id, v.reference_id) not in replaced]
    return kept + list(new)


def _narrow_to_reference(claims: list[Claim], reference_id: int) -> list[Claim]:
    """Copies of the claims that only cite this reference (re-verify one pair)."""
    return [c.model_copy(update={"reference_ids": [reference_id]}) for c in claims]


def _load_inputs(
    session_id: str, reference_id: int, claim_ids: list[int],
) -> tuple[Reference | None, list[Claim]]:
    """Reference + selected claims from the database."""
    from refcheck.db.claim_repo import get_claims

    db = get_db_session()
    try:
        db_ref = get_reference(db, session_id, reference_id)
        wanted = set(claim_ids)
        claims = [
            db_to_claim(c) for c in get_claims(db, session_id)
            if c.claim_number in wanted
        ]
    finally:
        db.close()
    ref = db_to_reference(db_ref) if db_ref else None
    return ref, _narrow_to_reference(claims, reference_id)


def _load_verifications(session_id: str) -> list[VerificationResult]:
    db = get_db_session()
    try:
        return [db_to_verification(v) for v in get_all_verifications(db, session_id)]
    finally:
        db.close()


async def reverify_reference(
    session_id: str,
    reference_id: int,
    claim_ids: list[int],
    reference_updates: dict[str, object] | None = None,
) -> list[VerificationResult]:
    """Background task: re-verify claims for one reference and persist.

    `reference_updates` (pdf_path, identity_status, ...) are applied to the
    stored reference first, so fields the DB may not store yet still count.
    Errors are logged, never raised (this runs after the HTTP response).
    """
    try:
        from refcheck.stages.verify_claims import verify_claims

        ref, claims = _load_inputs(session_id, reference_id, claim_ids)
        if ref is None or not claims:
            logger.warning(
                "Re-verify %s/ref %d: nothing to do (ref found=%s, %d claims)",
                session_id, reference_id, ref is not None, len(claims),
            )
            return []
        if reference_updates:
            ref = ref.model_copy(update=reference_updates)
        results = await verify_claims(claims, [ref])
        lock = _SESSION_LOCKS.setdefault(session_id, asyncio.Lock())
        async with lock:  # concurrent uploads must not drop each other's results
            merged = merge_verifications(_load_verifications(session_id), results)
            persist_verifications(session_id, merged)
        logger.info(
            "Re-verified %d claims for %s/ref %d", len(results), session_id, reference_id,
        )
        return results
    except Exception as exc:
        from refcheck.services.verify_outcome import describe_exception
        from refcheck.services.verify_runner import record_session_error

        logger.exception("Re-verification failed for %s/ref %d", session_id, reference_id)
        record_session_error(
            session_id,
            f"Re-verification of reference {reference_id} failed: "
            f"{describe_exception(exc)}",
        )
        return []


class RefreshMetadataResponse(BaseModel):
    """Response of POST .../references/{ref_id}/refresh-metadata."""

    reference_id: int
    changed_fields: list[str] = Field(default_factory=list)
    abstract_changed: bool = False
    abstract_source: str | None = None
    abstract_chars: int = 0
    previous_abstract_chars: int = 0
    open_access: OpenAccessHint = Field(default_factory=OpenAccessHint)
    claims_to_reverify: list[int] = Field(default_factory=list)
    reverification_started: bool = False


async def refresh_reference_metadata(
    db: DBSession, session_id: str, ref_id: int,
) -> RefreshMetadataResponse | None:
    """Re-run the abstract + open-access lookups for one reference and store changes.

    Claims to re-verify (the caller schedules `reverify_reference`) are chosen
    only when the abstract changed; None when the reference does not exist.
    """
    from refcheck.db.claim_repo import get_claims
    from refcheck.stages.resolve_gaps.metadata_refresh import refresh_metadata

    db_ref = get_reference(db, session_id, ref_id)
    if db_ref is None:
        return None
    outcome = await refresh_metadata(db_to_reference_with_access(db_ref))
    if outcome.changed_fields:
        update_reference(db, session_id, ref_id, **outcome.updates())
    claim_ids: list[int] = []
    if outcome.abstract_changed:
        claims = [db_to_claim(c) for c in get_claims(db, session_id)]
        verifications = [db_to_verification(v) for v in get_all_verifications(db, session_id)]
        claim_ids = find_claims_to_reverify(claims, verifications, ref_id)
    logger.info("Metadata refresh %s/ref %d: changed %s; %d claims to re-verify",
                session_id, ref_id, outcome.changed_fields or "nothing", len(claim_ids))
    ref = outcome.reference
    return RefreshMetadataResponse(
        reference_id=ref_id, changed_fields=outcome.changed_fields,
        abstract_changed=outcome.abstract_changed, abstract_source=ref.abstract_source,
        abstract_chars=len(ref.abstract_text or ""),
        previous_abstract_chars=outcome.previous_abstract_chars,
        open_access=outcome.open_access, claims_to_reverify=claim_ids,
        reverification_started=bool(claim_ids),
    )
