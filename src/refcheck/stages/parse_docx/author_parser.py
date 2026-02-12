"""Parse author names and titles from Vancouver-style reference strings."""

import re

# Pattern: single/double initials + surname, e.g. "A. Smith", "A.B. Smith-Jones"
_AUTHOR_NAME = re.compile(
    r"^(?:[A-Z]\.[\-]?){1,4}\s+[A-Z][\w\-'\u00C0-\u024F]+"  # Initial. Surname
    r"|^[A-Z][\w\-'\u00C0-\u024F]+\s+(?:[A-Z]\.[\-]?){1,4}$"  # Surname Initial.
    r"|^et\s+al\.?$",
    re.UNICODE,
)


def parse_authors_title(text: str) -> tuple[list[str], str]:
    """Parse author list and title from a reference string.

    Handles Vancouver-style refs like:
      [1] A. Courties, I. Kouki, Title of paper, Journal, Vol (Year).
      1. Author A, Author B. Title of paper. Journal. Year.
    """
    from refcheck.stages.parse_docx.reference_extractor import _NUMBERED_REF

    # Remove numbering prefix
    cleaned = _NUMBERED_REF.sub("", text).strip()

    # Strategy 1: Comma-separated segments — detect where authors end
    segments = re.split(r",\s*", cleaned)
    authors: list[str] = []
    title_start = 0

    for i, seg in enumerate(segments):
        seg = seg.strip()
        if _is_author_segment(seg):
            authors.append(seg)
            title_start = i + 1
        else:
            break

    if title_start > 0 and title_start < len(segments):
        remaining = ", ".join(segments[title_start:])
        title = _extract_title_from_remaining(remaining)
        return authors, title

    # Strategy 2: Period-split fallback for "Author A, Author B. Title."
    parts = re.split(r"(?<=[a-z])\.\s+", cleaned, maxsplit=2)
    if len(parts) >= 2:
        authors_str = parts[0]
        title = parts[1].rstrip(".")
        return _split_author_list(authors_str), title

    # Strategy 3: Return everything as title
    return [], cleaned


def _is_author_segment(segment: str) -> bool:
    """Check if a comma-separated segment looks like an author name."""
    seg = segment.strip().rstrip(".")
    if not seg or len(seg) < 2:
        return False
    if _AUTHOR_NAME.match(seg):
        return True
    return bool(re.match(r"^et\s+al\.?$", seg, re.IGNORECASE))


def _extract_title_from_remaining(text: str) -> str:
    """Extract the title from the portion after authors.

    In Vancouver style: 'Title of paper, Journal, Vol (Year) pages.'
    """
    parts = re.split(r",\s*", text)
    if len(parts) >= 2:
        title_parts: list[str] = []
        for part in parts:
            if _looks_like_journal_info(part) and title_parts:
                break
            title_parts.append(part)
        title = ", ".join(title_parts).strip().rstrip(".")
        return title
    return text.strip().rstrip(".")


def _looks_like_journal_info(segment: str) -> bool:
    """Heuristic: does this look like a journal name or volume info?"""
    seg = segment.strip()
    if re.match(r"^\d+\s*\(\d{4}\)", seg):
        return True
    return bool(re.search(r"\(\d{4}\)", seg) and len(seg) < 30)


def _split_author_list(text: str) -> list[str]:
    """Split an author string into individual author names."""
    text = re.sub(r"\bet\s+al\.?", "", text).strip().rstrip(",")
    if not text:
        return []
    raw = re.split(r"[;,]\s*", text)
    return [item.strip() for item in raw if item.strip() and len(item.strip()) > 1]
