"""Title-based fuzzy PDF matching using rapidfuzz."""

import logging
import re
from pathlib import Path

import fitz
from rapidfuzz import fuzz

from refcheck.models.matching import MatchResult
from refcheck.models.reference import Reference

logger = logging.getLogger(__name__)

# Confidence thresholds
_AUTO_ACCEPT = 0.90
_CONFIRM_THRESHOLD = 0.60


def extract_title_from_pdf(pdf_path: Path) -> str:
    """Extract the probable title from a PDF using multiple strategies.

    Strategies (in priority order):
    1. PDF metadata 'title' field
    2. Largest-font text on page 1 (academic papers use big font for title)
    3. Filename-based extraction (Author-Year-Title.pdf)
    """
    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        logger.warning("Cannot open PDF: %s", pdf_path.name)
        return ""

    try:
        # Strategy 1: PDF metadata title
        meta_title = _extract_from_metadata(doc)
        if meta_title and len(meta_title) > 15:
            return meta_title

        # Strategy 2: Largest font on first page
        font_title = _extract_by_font_size(doc)
        if font_title and len(font_title) > 15:
            return font_title

        # Strategy 3: Filename heuristic
        return _extract_from_filename(pdf_path)
    finally:
        doc.close()


def _extract_from_metadata(doc: fitz.Document) -> str:
    """Extract title from PDF metadata fields."""
    metadata = doc.metadata or {}
    title = str(metadata.get("title", "")).strip()

    # Filter out garbage metadata titles
    if title and len(title) > 10 and not title.endswith(".pdf") and "10." not in title[:5]:
        return title
    return ""


def _extract_by_font_size(doc: fitz.Document) -> str:
    """Extract title by finding the largest-font text on page 1.

    Academic papers almost always render the title in the largest
    font size on the first page.
    """
    if len(doc) == 0:
        return ""

    page = doc[0]
    text_dict = page.get_text("dict")
    blocks = text_dict.get("blocks", [])

    # Collect all text spans with their font sizes
    spans_by_size: dict[float, list[str]] = {}
    for block in blocks:
        if block.get("type") != 0:  # text block only
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                size = span.get("size", 0.0)
                if text and size > 0 and len(text) > 3:
                    if size not in spans_by_size:
                        spans_by_size[size] = []
                    spans_by_size[size].append(text)

    if not spans_by_size:
        return ""

    # Get the largest font size (exclude very small text)
    sorted_sizes = sorted(spans_by_size.keys(), reverse=True)

    # The title is typically in the largest or second-largest font
    for size in sorted_sizes[:3]:
        spans = spans_by_size[size]
        # Join spans of the same size into a title candidate
        candidate = " ".join(spans).strip()
        # Filter out short strings, page numbers, headers
        candidate = _clean_title_candidate(candidate)
        if candidate and len(candidate) > 15:
            return candidate

    return ""


def _clean_title_candidate(text: str) -> str:
    """Clean up a title candidate string."""
    # Remove common non-title patterns
    text = text.strip()
    # Remove "Abstract:" prefix if title accidentally includes it
    text = re.sub(r"^Abstract\s*:?\s*", "", text, flags=re.IGNORECASE)
    # Remove trailing metadata
    text = re.sub(r"\s*https?://\S+$", "", text)
    # Remove very short or purely numeric text
    if len(text) < 10 or text.replace(" ", "").isdigit():
        return ""
    return text


def _extract_from_filename(pdf_path: Path) -> str:
    """Extract title from a descriptive PDF filename.

    Handles patterns like:
      Author-Year-Title of paper.pdf
      Author_2020_Title.pdf
    """
    stem = pdf_path.stem
    # Remove author-year prefix: "Kim-2016-" or "Author_2020_"
    cleaned = re.sub(r"^[\w]+-\d{4}-", "", stem)
    cleaned = re.sub(r"^[\w]+_\d{4}_", "", cleaned)
    # Replace underscores and hyphens with spaces
    cleaned = cleaned.replace("_", " ").replace("-", " ")
    if len(cleaned) > 10:
        return cleaned
    return stem.replace("_", " ").replace("-", " ")


def match_by_title(
    references: list[Reference],
    pdf_path: Path,
) -> MatchResult | None:
    """Try to match a PDF to a reference using fuzzy title matching."""
    pdf_title = extract_title_from_pdf(pdf_path)
    if not pdf_title:
        return None

    best_score = 0.0
    best_ref: Reference | None = None
    alternatives: list[str] = []

    for ref in references:
        if not ref.title:
            continue
        score = fuzz.token_sort_ratio(
            pdf_title.lower(), ref.title.lower()
        )
        normalized_score = score / 100.0
        if normalized_score > best_score:
            if best_ref is not None and best_score >= _CONFIRM_THRESHOLD:
                alternatives.append(f"ref_{best_ref.id}")
            best_score = normalized_score
            best_ref = ref
        elif normalized_score >= _CONFIRM_THRESHOLD:
            alternatives.append(f"ref_{ref.id}")

    if best_ref is None or best_score < _CONFIRM_THRESHOLD:
        return None

    confidence = best_score * 0.95
    return MatchResult(
        reference_id=best_ref.id,
        pdf_path=str(pdf_path),
        confidence=round(confidence, 3),
        match_method="title_fuzzy",
        needs_user_confirmation=confidence < _AUTO_ACCEPT,
        candidate_alternatives=alternatives,
    )
