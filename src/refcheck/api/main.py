"""FastAPI application entry point."""

import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

# Load .env BEFORE any other imports that might need API keys
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_env_path = _PROJECT_ROOT / ".env"
load_dotenv(_env_path, override=True)

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from refcheck.api.middleware import RequestLoggingMiddleware  # noqa: E402
from refcheck.api.routes.claims import router as claims_router  # noqa: E402
from refcheck.api.routes.events import router as events_router  # noqa: E402
from refcheck.api.routes.health import router as health_router  # noqa: E402
from refcheck.api.routes.manuscript import router as manuscript_router  # noqa: E402
from refcheck.api.routes.references import router as references_router  # noqa: E402
from refcheck.api.routes.reports import router as reports_router  # noqa: E402
from refcheck.api.routes.results import router as results_router  # noqa: E402
from refcheck.api.routes.sessions import router as sessions_router  # noqa: E402
from refcheck.db.engine import init_db  # noqa: E402
from refcheck.utils.logging_config import setup_logging  # noqa: E402

_logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown hooks."""
    setup_logging()
    init_db()
    _logger.info(
        "RefCheck AI v3.0.0 started. DB_PATH=%s, ANTHROPIC_KEY=%s",
        os.getenv("REFCHECK_DB_PATH", "~/.refcheck/refcheck.db"),
        bool(os.environ.get("ANTHROPIC_API_KEY")),
    )
    yield
    _logger.info("RefCheck AI shutting down")


app = FastAPI(
    title="RefCheck AI",
    description="Scientific reference verification for biomedical manuscripts",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(sessions_router)
app.include_router(references_router)
app.include_router(events_router)
app.include_router(reports_router)
app.include_router(results_router)
app.include_router(claims_router)
app.include_router(manuscript_router)
