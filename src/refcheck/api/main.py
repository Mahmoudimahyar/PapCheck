"""FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from refcheck.api.routes.events import router as events_router
from refcheck.api.routes.health import router as health_router
from refcheck.api.routes.references import router as references_router
from refcheck.api.routes.reports import router as reports_router
from refcheck.api.routes.results import router as results_router
from refcheck.api.routes.sessions import router as sessions_router

app = FastAPI(
    title="RefCheck AI",
    description="Scientific reference verification for biomedical manuscripts",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "http://localhost:3003",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(sessions_router)
app.include_router(references_router)
app.include_router(events_router)
app.include_router(reports_router)
app.include_router(results_router)
