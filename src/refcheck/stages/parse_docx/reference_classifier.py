"""Classify reference type from raw text (V2).

Detects journal articles, book chapters, websites, preprints,
conference papers, and government reports.
"""

import logging

logger = logging.getLogger(__name__)

_URL_INDICATORS = ["http://", "https://", "www.", ".org/", ".gov/"]
_BOOK_INDICATORS = [
    "(eds.)", "(ed.)", "publisher", "press",
    "springer", "wiley", "elsevier", "pp.", "chapter",
]
_PREPRINT_INDICATORS = ["biorxiv", "medrxiv", "arxiv", "preprint"]
_CONFERENCE_INDICATORS = ["proceedings", "conference", "symposium"]
_GOVT_INDICATORS = [".gov", "government", "federal", "report"]


def classify_reference_type(
    raw_text: str, doi: str | None = None,
) -> str:
    """Classify reference type from raw text.

    Returns one of: journal_article, book_chapter, website,
    preprint, conference_paper, government_report.
    """
    text_lower = raw_text.lower()

    if _matches_any(text_lower, _PREPRINT_INDICATORS):
        return "preprint"

    if _matches_any(text_lower, _CONFERENCE_INDICATORS):
        return "conference_paper"

    if _matches_any(text_lower, _BOOK_INDICATORS):
        return "book_chapter"

    if _is_website(text_lower, doi):
        return "website"

    if _matches_any(text_lower, _GOVT_INDICATORS) and not doi:
        return "government_report"

    return "journal_article"


def _matches_any(text_lower: str, indicators: list[str]) -> bool:
    """Check if text contains any of the indicators."""
    return any(ind in text_lower for ind in indicators)


def _is_website(text_lower: str, doi: str | None) -> bool:
    """Check if reference is a website rather than a paper."""
    has_url = _matches_any(text_lower, _URL_INDICATORS)
    return has_url and not doi
