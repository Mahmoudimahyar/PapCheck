"""API middleware for error handling, request logging, and timing."""

import logging
import time
import uuid

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every request with timing, method, path, and status code."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = uuid.uuid4().hex[:8]
        start = time.time()

        # Skip SSE endpoints from detailed logging (they're long-lived)
        is_sse = "/events" in request.url.path

        if not is_sse:
            logger.info(
                "[%s] %s %s",
                request_id, request.method, request.url.path,
            )

        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = round((time.time() - start) * 1000)
            logger.exception(
                "[%s] %s %s -> 500 (%dms)",
                request_id, request.method, request.url.path, elapsed_ms,
            )
            raise

        elapsed_ms = round((time.time() - start) * 1000)

        if not is_sse:
            logger.info(
                "[%s] %s %s -> %d (%dms)",
                request_id,
                request.method,
                request.url.path,
                response.status_code,
                elapsed_ms,
            )

        # Add timing header for debugging
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-Ms"] = str(elapsed_ms)
        return response
