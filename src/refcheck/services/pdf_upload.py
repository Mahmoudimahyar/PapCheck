"""Accept a user-uploaded PDF for one reference (save, check, select claims)."""

import asyncio
import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from sqlmodel import Session as DBSession

from refcheck.db.claim_repo import get_claims
from refcheck.db.converters import db_to_claim, db_to_reference, db_to_verification
from refcheck.db.models import ReferenceDB
from refcheck.db.reference_repo import get_reference, update_reference
from refcheck.db.session_repo import get_session
from refcheck.db.verification_repo import get_all_verifications
from refcheck.services.reverifier import (
    SESSIONS_DIR,
    find_claims_to_reverify,
    save_uploaded_pdf,
)
from refcheck.stages.resolve_gaps.identity_check import (
    check_identity,
    read_first_pages_text,
)

logger = logging.getLogger(__name__)

MAX_PDF_BYTES = 100 * 1024 * 1024


class PdfUploadError(ValueError):
    """Upload rejected; carries the HTTP status code for the route."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class UploadPdfResponse(BaseModel):
    """Response of POST .../references/{ref_id}/upload-pdf."""

    reference_id: int
    pdf_matched: bool = True
    pdf_source: str = "user_upload"
    identity_status: Literal["verified", "unverified", "mismatch"] = "unverified"
    claims_to_reverify: list[int] = Field(default_factory=list)
    reverification_started: bool = False
    message: str = ""


def _session_pdf_dir(db: DBSession, session_id: str) -> Path:
    sess = get_session(db, session_id)
    if sess is None:
        raise PdfUploadError(404, "Session not found")
    return Path(sess.pdf_dir) if sess.pdf_dir else SESSIONS_DIR / session_id / "pdfs"


async def accept_reference_pdf(
    db: DBSession, session_id: str, ref_id: int, content: bytes,
) -> tuple[UploadPdfResponse, dict[str, object]]:
    """Save + identity-check the PDF, update the reference, pick claims.

    Returns the API response and the reference updates the background
    re-verification must apply (some fields may not be stored in the DB).
    """
    if not content.startswith(b"%PDF"):
        raise PdfUploadError(400, "File is not a valid PDF")
    if len(content) > MAX_PDF_BYTES:
        raise PdfUploadError(413, "PDF is larger than 100 MB")
    db_ref = get_reference(db, session_id, ref_id)
    if db_ref is None:
        raise PdfUploadError(404, "Reference not found")

    path = save_uploaded_pdf(_session_pdf_dir(db, session_id), ref_id, content)
    ref = db_to_reference(db_ref)
    page_text = await asyncio.to_thread(read_first_pages_text, path)
    identity = check_identity(ref, page_text)

    updates: dict[str, object] = {
        "pdf_path": path, "pdf_source": "user_upload", "source_status": "found",
        "identity_status": identity.status,
    }
    db_fields = {k: (str(v) if isinstance(v, Path) else v) for k, v in updates.items()}
    if "identity_status" not in ReferenceDB.model_fields:  # column added by WP-E
        db_fields.pop("identity_status")
    update_reference(db, session_id, ref_id, **db_fields)

    claims = [db_to_claim(c) for c in get_claims(db, session_id)]
    verifications = [db_to_verification(v) for v in get_all_verifications(db, session_id)]
    claim_ids = find_claims_to_reverify(claims, verifications, ref_id)
    logger.info(
        "Upload for %s/ref %d saved (%s); identity=%s (%s); %d claims to re-verify",
        session_id, ref_id, path.name, identity.status, identity.reason, len(claim_ids),
    )
    message = f"PDF saved; {len(claim_ids)} claim(s) will be re-verified."
    if identity.status == "mismatch":
        message += (
            " Warning: this PDF does not look like the cited paper "
            f"({identity.reason}); its claims will be reported as reference mismatch."
        )
    response = UploadPdfResponse(
        reference_id=ref_id,
        identity_status=identity.status,
        claims_to_reverify=claim_ids,
        reverification_started=bool(claim_ids),
        message=message,
    )
    return response, updates
