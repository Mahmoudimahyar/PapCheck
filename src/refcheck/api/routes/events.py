"""SSE endpoint for real-time pipeline events."""

import asyncio
import logging
from collections import defaultdict
from collections.abc import AsyncIterator

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse
from starlette.requests import Request

from refcheck.models.pipeline import PipelineEvent

router = APIRouter()
logger = logging.getLogger(__name__)

# Per-session event queues for live clients
_EVENT_QUEUES: dict[str, list[asyncio.Queue[PipelineEvent | None]]] = defaultdict(
    list
)

# Per-session event history for replay on late-connecting clients
_EVENT_HISTORY: dict[str, list[PipelineEvent]] = defaultdict(list)


@router.get("/api/sessions/{session_id}/events")
async def stream_events(session_id: str, request: Request) -> EventSourceResponse:
    """SSE endpoint for pipeline progress events."""

    async def event_generator() -> AsyncIterator[dict[str, str]]:
        queue: asyncio.Queue[PipelineEvent | None] = asyncio.Queue()
        _EVENT_QUEUES[session_id].append(queue)
        try:
            # Replay any buffered events the client missed
            for past_event in _EVENT_HISTORY.get(session_id, []):
                yield {"data": past_event.model_dump_json()}

            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    if event is None:
                        break
                    yield {"data": event.model_dump_json()}
                except TimeoutError:
                    # Send keepalive
                    yield {"data": "{}"}
        finally:
            if queue in _EVENT_QUEUES[session_id]:
                _EVENT_QUEUES[session_id].remove(queue)

    return EventSourceResponse(event_generator())


async def emit_event(session_id: str, event: PipelineEvent) -> None:
    """Push an event to all SSE listeners and buffer it for late joiners."""
    # Buffer for replay
    _EVENT_HISTORY[session_id].append(event)

    # Push to live listeners
    queues = _EVENT_QUEUES.get(session_id, [])
    for queue in queues:
        await queue.put(event)


async def close_event_stream(session_id: str) -> None:
    """Signal end of event stream for a session."""
    queues = _EVENT_QUEUES.get(session_id, [])
    for queue in queues:
        await queue.put(None)


def clear_event_history(session_id: str) -> None:
    """Clear buffered events for a session (cleanup)."""
    _EVENT_HISTORY.pop(session_id, None)
