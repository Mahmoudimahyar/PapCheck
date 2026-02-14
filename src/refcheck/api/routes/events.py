"""SSE endpoint for real-time pipeline events."""

import asyncio
import logging
from collections import defaultdict
from collections.abc import AsyncIterator

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse
from starlette.requests import Request

from refcheck.db.converters import db_to_event, event_to_db
from refcheck.db.engine import get_db_session
from refcheck.db.event_repo import get_events, save_event
from refcheck.models.pipeline import PipelineEvent

router = APIRouter()
logger = logging.getLogger(__name__)

# Live SSE queues (still in-memory for real-time push)
_EVENT_QUEUES: dict[str, list[asyncio.Queue[PipelineEvent | None]]] = defaultdict(
    list
)


@router.get("/api/sessions/{session_id}/events")
async def stream_events(
    session_id: str, request: Request,
) -> EventSourceResponse:
    """SSE endpoint for pipeline progress events."""

    async def event_generator() -> AsyncIterator[dict[str, str]]:
        queue: asyncio.Queue[PipelineEvent | None] = asyncio.Queue()
        _EVENT_QUEUES[session_id].append(queue)
        try:
            # Replay past events from database
            db = get_db_session()
            try:
                past_events = get_events(db, session_id)
                for db_ev in past_events:
                    yield {"data": db_to_event(db_ev).model_dump_json()}
            finally:
                db.close()

            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    if event is None:
                        break
                    yield {"data": event.model_dump_json()}
                except TimeoutError:
                    yield {"data": "{}"}
        finally:
            if queue in _EVENT_QUEUES[session_id]:
                _EVENT_QUEUES[session_id].remove(queue)

    return EventSourceResponse(event_generator())


async def emit_event(session_id: str, event: PipelineEvent) -> None:
    """Push event to live SSE listeners and persist to database."""
    # Persist to database
    db = get_db_session()
    try:
        db_event = event_to_db(event, session_id)
        save_event(db, db_event)
    finally:
        db.close()

    # Push to live listeners
    queues = _EVENT_QUEUES.get(session_id, [])
    for queue in queues:
        await queue.put(event)


async def close_event_stream(session_id: str) -> None:
    """Signal end of event stream for a session."""
    queues = _EVENT_QUEUES.get(session_id, [])
    for queue in queues:
        await queue.put(None)
