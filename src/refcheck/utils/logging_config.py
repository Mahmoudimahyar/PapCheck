"""Structured logging configuration for RefCheck AI."""

import logging
import os
import sys


def setup_logging() -> None:
    """Configure structured logging for the entire application.

    Sets up a single handler with a consistent format. Log level is
    configurable via REFCHECK_LOG_LEVEL environment variable.
    """
    level_name = os.getenv("REFCHECK_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    fmt = (
        "%(asctime)s | %(levelname)-7s | %(name)-30s | %(message)s"
    )
    date_fmt = "%Y-%m-%d %H:%M:%S"

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt, datefmt=date_fmt))

    root = logging.getLogger()
    root.setLevel(level)

    # Remove existing handlers to avoid duplicates on reload
    for existing in root.handlers[:]:
        root.removeHandler(existing)

    root.addHandler(handler)

    # Suppress noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("litellm").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
