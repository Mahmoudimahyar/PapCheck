"""Claim CRUD operations for the database."""

import logging

from sqlmodel import Session, select

from refcheck.db.models import ClaimDB

logger = logging.getLogger(__name__)


def save_claims(
    db: Session, session_id: str, claims: list[ClaimDB],
) -> None:
    """Insert or replace all claims for a session."""
    stmt = select(ClaimDB).where(ClaimDB.session_id == session_id)
    existing = db.exec(stmt).all()
    for row in existing:
        db.delete(row)

    for claim in claims:
        claim.session_id = session_id
        db.add(claim)
    db.commit()


def get_claims(db: Session, session_id: str) -> list[ClaimDB]:
    """Get all claims for a session ordered by claim number."""
    stmt = (
        select(ClaimDB)
        .where(ClaimDB.session_id == session_id)
        .order_by(ClaimDB.claim_number)  # type: ignore[arg-type]
    )
    return list(db.exec(stmt).all())


def update_claim(
    db: Session, session_id: str, claim_number: int, **kwargs: object,
) -> ClaimDB | None:
    """Update a claim's fields."""
    stmt = (
        select(ClaimDB)
        .where(ClaimDB.session_id == session_id)
        .where(ClaimDB.claim_number == claim_number)
    )
    claim = db.exec(stmt).first()
    if not claim:
        return None
    for key, value in kwargs.items():
        setattr(claim, key, value)
    db.add(claim)
    db.commit()
    db.refresh(claim)
    return claim


def delete_claim(
    db: Session, session_id: str, claim_number: int,
) -> bool:
    """Delete a claim from the session."""
    stmt = (
        select(ClaimDB)
        .where(ClaimDB.session_id == session_id)
        .where(ClaimDB.claim_number == claim_number)
    )
    claim = db.exec(stmt).first()
    if not claim:
        return False
    db.delete(claim)
    db.commit()
    return True
