"""Detect and parse in-text citations from manuscript text."""

import logging
import re
from typing import Literal

from refcheck.models.reference import InTextCitation

logger = logging.getLogger(__name__)

# Numbered citation patterns: [1], [1,2], [1-5], [1, 3-5, 7]
_NUMBERED_CITATION = re.compile(
    r"\[(\d+(?:\s*[-–]\s*\d+)?(?:\s*,\s*\d+(?:\s*[-–]\s*\d+)?)*)\]"
)

# Author-year citation: (Smith, 2020) or (Smith et al., 2020) or (Smith & Jones, 2020)
_AUTHOR_YEAR_CITATION = re.compile(
    r"\(([A-Z][a-z]+(?:\s+(?:et\s+al\.|&\s+[A-Z][a-z]+))?(?:,?\s*\d{4}))\)"
)

CitationStyle = Literal["numbered", "author_year", "footnote", "unknown"]


def detect_citation_style(text: str) -> CitationStyle:
    """Detect the citation style used in the manuscript text."""
    numbered_count = len(_NUMBERED_CITATION.findall(text))
    author_year_count = len(_AUTHOR_YEAR_CITATION.findall(text))

    if numbered_count > author_year_count and numbered_count >= 2:
        return "numbered"
    if author_year_count > numbered_count and author_year_count >= 2:
        return "author_year"
    if numbered_count >= 1:
        return "numbered"
    if author_year_count >= 1:
        return "author_year"
    return "unknown"


def expand_citation_range(range_str: str) -> list[int]:
    """Expand a citation range string into individual reference IDs.

    Examples: "1-5, 7" -> [1, 2, 3, 4, 5, 7]
              "3" -> [3]
              "1, 3-5, 7" -> [1, 3, 4, 5, 7]
    """
    ids: list[int] = []
    # Split on commas
    parts = re.split(r"\s*,\s*", range_str.strip())
    for part in parts:
        part = part.strip()
        # Check for range (1-5 or 1–5)
        range_match = re.match(r"(\d+)\s*[-–]\s*(\d+)", part)
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2))
            ids.extend(range(start, end + 1))
        elif part.isdigit():
            ids.append(int(part))
    return ids


def find_citations_in_text(text: str) -> list[InTextCitation]:
    """Find all citation markers in a text string."""
    citations: list[InTextCitation] = []

    # Find numbered citations
    for match in _NUMBERED_CITATION.finditer(text):
        ref_ids = expand_citation_range(match.group(1))
        citations.append(
            InTextCitation(
                raw_text=match.group(0),
                position=match.start(),
                reference_ids=ref_ids,
            )
        )

    # Find author-year citations
    for match in _AUTHOR_YEAR_CITATION.finditer(text):
        citations.append(
            InTextCitation(
                raw_text=match.group(0),
                position=match.start(),
                reference_ids=[],
            )
        )

    # Sort by position
    citations.sort(key=lambda c: c.position)
    return citations
