"""Session CRUD operations for the database."""

import logging
from datetime import UTC, datetime

from sqlmodel import Session, col, select

from refcheck.db.models import (
    ClaimDB,
    PipelineEventDB,
    ReferenceDB,
    SessionDB,
    VerificationDB,
)

logger = logging.getLogger(__name__)


def create_session(db: Session, session_data: SessionDB) -> SessionDB:
    """Insert a new session into the database."""
    db.add(session_data)
    db.commit()
    db.refresh(session_data)
    return session_data


def get_session(db: Session, session_id: str) -> SessionDB | None:
    """Retrieve a session by ID."""
    return db.get(SessionDB, session_id)


def update_session(
    db: Session, session_id: str, **kwargs: object,
) -> SessionDB | None:
    """Update session fields by ID."""
    session = db.get(SessionDB, session_id)
    if not session:
        return None
    for key, value in kwargs.items():
        setattr(session, key, value)
    session.updated_at = datetime.now(UTC)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def list_sessions(
    db: Session, limit: int = 20, offset: int = 0,
) -> tuple[list[SessionDB], int]:
    """List sessions with pagination, newest first."""
    total_stmt = select(SessionDB)
    total = len(db.exec(total_stmt).all())

    stmt = (
        select(SessionDB)
        .order_by(col(SessionDB.created_at).desc())
        .offset(offset)
        .limit(limit)
    )
    sessions = list(db.exec(stmt).all())
    return sessions, total


def delete_session(db: Session, session_id: str) -> bool:
    """Delete a session and all associated data."""
    session = db.get(SessionDB, session_id)
    if not session:
        return False

    # Delete associated data in order (foreign key safety)
    _delete_related(db, PipelineEventDB, session_id)
    _delete_related(db, VerificationDB, session_id)
    _delete_related(db, ClaimDB, session_id)
    _delete_related(db, ReferenceDB, session_id)

    db.delete(session)
    db.commit()
    logger.info("Deleted session %s and all associated data", session_id)
    return True


def _delete_related(
    db: Session, model: type[ReferenceDB | ClaimDB | VerificationDB | PipelineEventDB],
    session_id: str,
) -> None:
    """Delete all rows for a given session in a related table."""
    stmt = select(model).where(model.session_id == session_id)
    rows = db.exec(stmt).all()
    for row in rows:
        db.delete(row)
