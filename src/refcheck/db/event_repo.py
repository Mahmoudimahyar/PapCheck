"""Pipeline event CRUD operations for the database."""

import logging

from sqlmodel import Session, select

from refcheck.db.models import PipelineEventDB

logger = logging.getLogger(__name__)


def save_event(db: Session, event: PipelineEventDB) -> None:
    """Insert a pipeline event."""
    db.add(event)
    db.commit()


def get_events(db: Session, session_id: str) -> list[PipelineEventDB]:
    """Get all events for a session, ordered chronologically."""
    stmt = (
        select(PipelineEventDB)
        .where(PipelineEventDB.session_id == session_id)
        .order_by(PipelineEventDB.created_at)  # type: ignore[arg-type]
    )
    return list(db.exec(stmt).all())


def clear_events(db: Session, session_id: str) -> None:
    """Delete all events for a session."""
    stmt = select(PipelineEventDB).where(
        PipelineEventDB.session_id == session_id,
    )
    events = db.exec(stmt).all()
    for event in events:
        db.delete(event)
    db.commit()
