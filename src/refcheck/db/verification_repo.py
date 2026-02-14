"""Verification result CRUD operations for the database."""

import logging

from sqlmodel import Session, select

from refcheck.db.models import VerificationDB

logger = logging.getLogger(__name__)


def save_verifications(
    db: Session, session_id: str, results: list[VerificationDB],
) -> None:
    """Insert or replace all verifications for a session."""
    stmt = select(VerificationDB).where(
        VerificationDB.session_id == session_id,
    )
    existing = db.exec(stmt).all()
    for row in existing:
        db.delete(row)

    for v in results:
        v.session_id = session_id
        db.add(v)
    db.commit()


def get_verifications(
    db: Session,
    session_id: str,
    verdict: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[VerificationDB], int]:
    """Get verifications with optional verdict filter and pagination."""
    stmt = select(VerificationDB).where(
        VerificationDB.session_id == session_id,
    )
    if verdict and verdict != "all":
        stmt = stmt.where(VerificationDB.verdict == verdict)
    all_results = list(db.exec(stmt).all())
    total = len(all_results)

    start = (page - 1) * per_page
    end = start + per_page
    return all_results[start:end], total


def get_all_verifications(
    db: Session, session_id: str,
) -> list[VerificationDB]:
    """Get all verifications for a session (no pagination)."""
    stmt = select(VerificationDB).where(
        VerificationDB.session_id == session_id,
    )
    return list(db.exec(stmt).all())


def update_verification(
    db: Session, session_id: str, claim_id: int, **kwargs: object,
) -> VerificationDB | None:
    """Update a verification's fields by session and claim ID."""
    stmt = (
        select(VerificationDB)
        .where(VerificationDB.session_id == session_id)
        .where(VerificationDB.claim_id == claim_id)
    )
    verification = db.exec(stmt).first()
    if not verification:
        return None
    for key, value in kwargs.items():
        setattr(verification, key, value)
    db.add(verification)
    db.commit()
    db.refresh(verification)
    return verification
