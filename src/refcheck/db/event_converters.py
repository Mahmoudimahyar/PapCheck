"""Convert between pipeline event/session Pydantic and DB models."""

import json

from refcheck.db.models import PipelineEventDB, SessionDB
from refcheck.models.pipeline import PipelineEvent, Session


def session_to_db(session: Session) -> SessionDB:
    """Convert a Pydantic Session to a SessionDB row."""
    return SessionDB(
        id=session.id,
        status=session.status,
        created_at=session.created_at,
        manuscript_filename=session.manuscript_filename,
        pdf_count=session.pdf_count,
    )


def db_to_session(db_sess: SessionDB) -> Session:
    """Convert a SessionDB row to a Pydantic Session."""
    return Session(
        id=db_sess.id,
        status=db_sess.status,  # type: ignore[arg-type]
        created_at=db_sess.created_at,
        manuscript_filename=db_sess.manuscript_filename,
        pdf_count=db_sess.pdf_count,
    )


def event_to_db(event: PipelineEvent, session_id: str) -> PipelineEventDB:
    """Convert a Pydantic PipelineEvent to a PipelineEventDB row."""
    return PipelineEventDB(
        session_id=session_id,
        stage=event.stage,
        status=event.status,
        progress_json=json.dumps(event.progress) if event.progress else None,
        message=event.message,
        elapsed_seconds=event.elapsed_seconds,
        intervention_json=(
            json.dumps(event.intervention) if event.intervention else None
        ),
    )


def db_to_event(db_ev: PipelineEventDB) -> PipelineEvent:
    """Convert a PipelineEventDB row to a Pydantic PipelineEvent."""
    return PipelineEvent(
        stage=db_ev.stage,
        status=db_ev.status,  # type: ignore[arg-type]
        progress=json.loads(db_ev.progress_json) if db_ev.progress_json else None,
        message=db_ev.message,
        elapsed_seconds=db_ev.elapsed_seconds,
        intervention=(
            json.loads(db_ev.intervention_json) if db_ev.intervention_json else None
        ),
    )
