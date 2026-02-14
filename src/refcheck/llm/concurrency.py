"""Concurrency control for LLM and API calls."""

import asyncio
import logging
import os

logger = logging.getLogger(__name__)

_DEFAULT_LLM_CONCURRENCY = 2
_DEFAULT_API_CONCURRENCY = 10

_llm_semaphore: asyncio.Semaphore | None = None
_api_semaphore: asyncio.Semaphore | None = None


def get_llm_semaphore() -> asyncio.Semaphore:
    """Get or create the LLM concurrency semaphore (lazy singleton).

    Limits concurrent LLM calls to avoid rate limits and control costs.
    Configure via REFCHECK_LLM_CONCURRENCY environment variable.
    """
    global _llm_semaphore  # noqa: PLW0603
    if _llm_semaphore is None:
        limit = int(os.getenv(
            "REFCHECK_LLM_CONCURRENCY",
            str(_DEFAULT_LLM_CONCURRENCY),
        ))
        _llm_semaphore = asyncio.Semaphore(limit)
        logger.info("LLM semaphore created with limit=%d", limit)
    return _llm_semaphore


def get_api_semaphore() -> asyncio.Semaphore:
    """Get or create the API concurrency semaphore (lazy singleton).

    Limits concurrent external API calls (PubMed, CrossRef, etc.).
    Configure via REFCHECK_API_CONCURRENCY environment variable.
    """
    global _api_semaphore  # noqa: PLW0603
    if _api_semaphore is None:
        limit = int(os.getenv(
            "REFCHECK_API_CONCURRENCY",
            str(_DEFAULT_API_CONCURRENCY),
        ))
        _api_semaphore = asyncio.Semaphore(limit)
        logger.info("API semaphore created with limit=%d", limit)
    return _api_semaphore


def reset_semaphores() -> None:
    """Reset semaphores (for testing)."""
    global _llm_semaphore, _api_semaphore  # noqa: PLW0603
    _llm_semaphore = None
    _api_semaphore = None
