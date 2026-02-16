"""Post-download PDF validation and supplement detection."""

import logging
from pathlib import Path

import fitz
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

_SUPPLEMENT_KEYWORDS = (
    "_si_", "supplement", "/si/", "supporting", "appendix",
)
_MAIN_PAPER_KEYWORDS = ("/pdf/", "/full/", "/article/")

_SUPPLEMENT_PAGE_INDICATORS = (
    "supplementary information",
    "supplementary material",
    "supplementary data",
    "supporting information",
    "supplemental figures",
)
_MIN_TEXT_LENGTH = 2000
_TITLE_MATCH_THRESHOLD = 70


def score_pdf_url(url: str) -> int:
    """Score a PDF URL: higher = more likely the main paper."""
    score = 50
    lower = url.lower()
    for keyword in _SUPPLEMENT_KEYWORDS:
        if keyword in lower:
            return score - 40
    for keyword in _MAIN_PAPER_KEYWORDS:
        if keyword in lower:
            score += 20
    return score


def validate_downloaded_pdf(path: Path, title: str) -> bool:
    """Check if a downloaded PDF is the actual paper (not supplement).

    Returns False if:
    - First page says "Supplementary Information"
    - Title doesn't fuzzy-match first page
    - Total text < 2000 chars (likely just figures)
    """
    try:
        doc = fitz.open(str(path))
        if len(doc) == 0:
            doc.close()
            return False
        first_page_text = doc[0].get_text("text").strip().lower()
        total_text_len = sum(
            len(doc[i].get_text("text")) for i in range(min(3, len(doc)))
        )
        doc.close()
    except Exception as exc:
        logger.warning("PDF validation failed for %s: %s", path, exc)
        return False

    # Check supplement indicators on first page
    for indicator in _SUPPLEMENT_PAGE_INDICATORS:
        if indicator in first_page_text:
            logger.info("PDF %s is a supplement (contains '%s')", path.name, indicator)
            return False

    # Check total text length
    if total_text_len < _MIN_TEXT_LENGTH:
        logger.info("PDF %s has too little text (%d chars)", path.name, total_text_len)
        return False

    # Check title match
    if title:
        ratio = fuzz.partial_ratio(title.lower(), first_page_text[:500])
        if ratio < _TITLE_MATCH_THRESHOLD:
            logger.info(
                "PDF %s title mismatch (ratio=%d)", path.name, ratio,
            )
            return False

    return True
