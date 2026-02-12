"""Health check endpoint."""

import logging
import os

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "ok"
    grobid: str = "unavailable"
    version: str = "0.1.0"


@router.get("/api/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Return service health status."""
    return HealthResponse()


@router.get("/api/debug/llm-test")
async def debug_llm_test() -> dict[str, str]:
    """Quick LLM test — remove after debugging."""
    from refcheck.llm.client import call_llm
    from refcheck.stages.extract_claims.claim_parser import (
        ClaimExtractionResponse,
    )

    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    try:
        result = await call_llm(
            template="claim_extraction",
            variables={
                "section_text": "Drug X reduces pain by 30% [1].",
                "reference_list": "[1] Smith et al. (2023)",
                "section_heading": "Test",
            },
            output_model=ClaimExtractionResponse,
        )
        return {
            "status": "ok",
            "api_key_set": str(has_key),
            "claims_found": str(len(result.claims)),
        }
    except Exception as exc:
        return {
            "status": "error",
            "api_key_set": str(has_key),
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
        }
