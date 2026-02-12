"""Find relevant sections in PDFs for claim verification (RAG)."""

import logging
import re
from pathlib import Path

import fitz

from refcheck.models.claim import Claim

logger = logging.getLogger(__name__)

# Common English stop words to exclude from keyword matching
_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "must", "and", "or",
    "but", "if", "than", "that", "which", "who", "whom", "this", "these",
    "those", "it", "its", "of", "in", "to", "for", "with", "on", "at",
    "by", "from", "as", "into", "about", "between", "through", "during",
    "before", "after", "not", "no", "nor", "so", "very", "also", "both",
    "each", "more", "most", "other", "some", "such", "only", "own",
    "same", "then", "there", "here", "when", "where", "how", "all", "any",
    "et", "al",
})

_MIN_SCORE_THRESHOLD = 0.1
_ABSTRACT_FALLBACK_CHARS = 500
_SHORT_PDF_CHARS = 2000


def find_relevant_sections(
    claim: Claim,
    pdf_path: Path,
    max_sections: int = 5,
) -> list[str]:
    """Find the most relevant text sections from a PDF for a claim.

    Uses keyword overlap scoring to select the top sections.
    Returns empty list if PDF cannot be read.
    """
    full_text = _extract_pdf_text(pdf_path)
    if not full_text:
        return []

    # Short PDFs (abstract only) — return full text
    if len(full_text) < _SHORT_PDF_CHARS:
        return [full_text]

    paragraphs = _split_into_paragraphs(full_text)
    if not paragraphs:
        return [full_text[:_ABSTRACT_FALLBACK_CHARS]]

    keywords = _extract_keywords(claim.extracted_claim)
    numbers = _extract_numbers(claim.extracted_claim)

    scored = []
    for para in paragraphs:
        score = _score_section(para, keywords, numbers)
        if score > _MIN_SCORE_THRESHOLD:
            scored.append((score, para))

    scored.sort(key=lambda x: x[0], reverse=True)

    if not scored:
        # Fallback: return the abstract (first ~500 chars)
        return [full_text[:_ABSTRACT_FALLBACK_CHARS]]

    return [text for _, text in scored[:max_sections]]


def _extract_pdf_text(pdf_path: Path) -> str:
    """Extract all text from a PDF using PyMuPDF."""
    try:
        doc = fitz.open(str(pdf_path))
        pages = [page.get_text() for page in doc]
        doc.close()
        return "\n".join(pages).strip()
    except Exception:
        logger.warning("Could not extract text from PDF: %s", pdf_path)
        return ""


def _split_into_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs by double newlines or heading patterns."""
    # Split on double newlines, section breaks
    chunks = re.split(r"\n\s*\n", text)
    # Filter out very short fragments
    return [c.strip() for c in chunks if len(c.strip()) > 50]


def _extract_keywords(text: str) -> set[str]:
    """Extract meaningful keywords from claim text."""
    words = re.findall(r"[a-zA-Z]{3,}", text.lower())
    return {w for w in words if w not in _STOP_WORDS}


def _extract_numbers(text: str) -> set[str]:
    """Extract numbers and percentages from claim text."""
    return set(re.findall(r"\d+\.?\d*%?", text))


def _score_section(
    section: str,
    keywords: set[str],
    numbers: set[str],
) -> float:
    """Score a section's relevance to a claim based on keyword overlap."""
    if not keywords:
        return 0.0

    section_lower = section.lower()
    keyword_hits = sum(1 for kw in keywords if kw in section_lower)
    keyword_score = keyword_hits / len(keywords) if keywords else 0.0

    # Boost for matching numbers (important for factual claims)
    number_hits = sum(1 for n in numbers if n in section)
    number_boost = min(number_hits * 0.15, 0.3)

    return keyword_score + number_boost
