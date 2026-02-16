"""Find relevant sections in PDFs for claim verification (RAG)."""

import logging
import re
import unicodedata
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
_MAX_SECTION_WORDS = 2000


def find_relevant_sections(
    claim: Claim,
    pdf_path: Path,
    max_sections: int = 5,
) -> list[str]:
    """Find the most relevant text sections from a PDF for a claim.

    Uses keyword overlap scoring to select the top sections.
    Returns empty list if PDF cannot be read.
    """
    pairs = find_relevant_sections_with_headings(claim, pdf_path, max_sections)
    return [text for _, text in pairs]


def find_relevant_sections_with_headings(
    claim: Claim,
    pdf_path: Path,
    max_sections: int = 5,
) -> list[tuple[str, str]]:
    """Find sections returning (heading, text) pairs.

    Returns empty list if PDF cannot be read.
    """
    full_text = _extract_pdf_text(pdf_path)
    if not full_text:
        return []

    if len(full_text) < _SHORT_PDF_CHARS:
        return [("Full Text", full_text)]

    paragraphs = _split_into_paragraphs(full_text)
    if not paragraphs:
        return [("Abstract", full_text[:_ABSTRACT_FALLBACK_CHARS])]

    keywords = _extract_keywords(claim.extracted_claim)
    numbers = _extract_numbers(claim.extracted_claim)

    scored: list[tuple[float, str, str]] = []
    for para in paragraphs:
        score = _score_section(para, keywords, numbers)
        if score > _MIN_SCORE_THRESHOLD:
            heading = _guess_heading(para)
            scored.append((score, heading, para))

    scored.sort(key=lambda x: x[0], reverse=True)

    if not scored:
        return [("Abstract", sanitize_text(full_text[:_ABSTRACT_FALLBACK_CHARS]))]

    return [
        (h, sanitize_text(text)) for _, h, text in scored[:max_sections]
    ]


def sanitize_text(text: str) -> str:
    """Clean text for LLM consumption: remove nulls, normalize unicode."""
    # Remove null bytes
    text = text.replace("\x00", "")
    # Remove non-printable control characters (keep newlines/tabs)
    text = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    # Normalize unicode (NFC)
    text = unicodedata.normalize("NFC", text)
    # Collapse excessive whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Truncate very long sections
    words = text.split()
    if len(words) > _MAX_SECTION_WORDS:
        text = " ".join(words[:_MAX_SECTION_WORDS]) + "\n[truncated]"
    return text.strip()


_HEADING_PATTERN = re.compile(
    r"^(Abstract|Introduction|Methods|Results|Discussion|Conclusion"
    r"|Background|Materials|References|Acknowledgments)",
    re.IGNORECASE | re.MULTILINE,
)


def _guess_heading(paragraph: str) -> str:
    """Try to infer a section heading from a paragraph's first line."""
    first_line = paragraph.split("\n", maxsplit=1)[0].strip()
    match = _HEADING_PATTERN.match(first_line)
    if match:
        return match.group(1).title()
    # If first line is short and looks like a heading, use it
    if len(first_line) < 60 and first_line[0:1].isupper():
        return first_line
    return "Source Section"


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
