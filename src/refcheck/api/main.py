"""FastAPI application entry point."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env BEFORE any other imports that might need API keys
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_env_path = _PROJECT_ROOT / ".env"
_loaded = load_dotenv(_env_path, override=True)

_logger = logging.getLogger(__name__)
_logger.info(
    "dotenv loaded=%s path=%s exists=%s ANTHROPIC_KEY_SET=%s",
    _loaded, _env_path, _env_path.exists(),
    bool(os.environ.get("ANTHROPIC_API_KEY")),
)
# Also print to stdout for visibility in uvicorn output
print(
    f"[RefCheck] .env loaded={_loaded} path={_env_path} "
    f"exists={_env_path.exists()} "
    f"ANTHROPIC_KEY_SET={bool(os.environ.get('ANTHROPIC_API_KEY'))} "
    f"OPENAI_KEY_SET={bool(os.environ.get('OPENAI_API_KEY'))}",
)

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from refcheck.api.routes.claims import router as claims_router  # noqa: E402
from refcheck.api.routes.events import router as events_router  # noqa: E402
from refcheck.api.routes.health import router as health_router  # noqa: E402
from refcheck.api.routes.references import router as references_router  # noqa: E402
from refcheck.api.routes.reports import router as reports_router  # noqa: E402
from refcheck.api.routes.results import router as results_router  # noqa: E402
from refcheck.api.routes.sessions import router as sessions_router  # noqa: E402

app = FastAPI(
    title="RefCheck AI",
    description="Scientific reference verification for biomedical manuscripts",
    version="0.1.0",
)

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
