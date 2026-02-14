"""Reference CRUD operations for the database."""

import logging

from sqlmodel import Session, select

from refcheck.db.models import ReferenceDB

logger = logging.getLogger(__name__)


def save_references(
    db: Session, session_id: str, refs: list[ReferenceDB],
) -> None:
    """Insert or replace all references for a session."""
    # Remove existing references for this session
    stmt = select(ReferenceDB).where(ReferenceDB.session_id == session_id)
    existing = db.exec(stmt).all()
    for row in existing:
        db.delete(row)

    for ref in refs:
        ref.session_id = session_id
        db.add(ref)
    db.commit()


def get_references(
    db: Session,
    session_id: str,
    status: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[ReferenceDB], int]:
    """Get references with optional status filter and pagination."""
    stmt = select(ReferenceDB).where(ReferenceDB.session_id == session_id)
    if status and status != "all":
        stmt = stmt.where(ReferenceDB.source_status == status)
    all_refs = list(db.exec(stmt).all())
    total = len(all_refs)

    # Sort by ref_number and paginate
    all_refs.sort(key=lambda r: r.ref_number)
    start = (page - 1) * per_page
    end = start + per_page
    return all_refs[start:end], total


def get_reference(
    db: Session, session_id: str, ref_number: int,
) -> ReferenceDB | None:
    """Get a single reference by session and reference number."""
    stmt = (
        select(ReferenceDB)
        .where(ReferenceDB.session_id == session_id)
        .where(ReferenceDB.ref_number == ref_number)
    )
    return db.exec(stmt).first()


def get_all_references(
    db: Session, session_id: str,
) -> list[ReferenceDB]:
    """Get all references for a session (no pagination)."""
    stmt = (
        select(ReferenceDB)
        .where(ReferenceDB.session_id == session_id)
        .order_by(ReferenceDB.ref_number)  # type: ignore[arg-type]
    )
    return list(db.exec(stmt).all())


def update_reference(
    db: Session, session_id: str, ref_number: int, **kwargs: object,
) -> ReferenceDB | None:
    """Update a reference's fields."""
    ref = get_reference(db, session_id, ref_number)
    if not ref:
        return None
    for key, value in kwargs.items():
        setattr(ref, key, value)
    db.add(ref)
    db.commit()
    db.refresh(ref)
    return ref
