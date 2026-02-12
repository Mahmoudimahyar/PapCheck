"""Text processing utilities."""

import re


def normalize_whitespace(text: str) -> str:
    """Collapse multiple whitespace characters to single spaces."""
    return re.sub(r"\s+", " ", text).strip()
