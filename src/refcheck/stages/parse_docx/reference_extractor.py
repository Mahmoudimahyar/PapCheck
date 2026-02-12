"""Extract and parse individual references from the reference section."""

import logging
import re

from refcheck.models.reference import Reference
from refcheck.stages.parse_docx.author_parser import parse_authors_title

logger = logging.getLogger(__name__)

# Patterns for detecting reference section headings
_HEADING_KEYWORDS = re.compile(
    r"^\s*(references|bibliography|works\s+cited|literature\s+cited"
    r"|reference\s+list|cited\s+literature|sources)\s*$",
    re.IGNORECASE,
)

# Numbered reference patterns at start of line/paragraph:
#   [1] text     [12] text     [139] text
#   1. text      12. text      139. text
#   1) text      12) text
#   (1) text     (12) text
_NUMBERED_REF = re.compile(
    r"^\s*"
    r"(?:"
    r"\[(\d{1,4})\]"          # [1] or [139]
    r"|(\d{1,4})[\.\)]"       # 1. or 1)
    r"|\((\d{1,4})\)"         # (1)
    r")"
    r"\s+",                    # must be followed by whitespace
)

# DOI patterns
_DOI_PATTERN = re.compile(
    r"(?:doi[:\s]*|https?://(?:dx\.)?doi\.org/)(10\.\d{4,}/\S+)",
    re.IGNORECASE,
)
_DOI_BARE = re.compile(r"\b(10\.\d{4,}/\S+)")

# PMID pattern
_PMID_PATTERN = re.compile(
    r"(?:PMID|PubMed)[:\s]*(\d{6,9})",
    re.IGNORECASE,
)

# Year pattern
_YEAR_PATTERN = re.compile(r"\b((?:19|20)\d{2})\b")


def is_reference_heading(text: str) -> bool:
    """Check if the given text looks like a reference section heading."""
    return bool(_HEADING_KEYWORDS.match(text.strip()))


def extract_doi(text: str) -> str | None:
    """Extract DOI from reference text, returning normalized form."""
    match = _DOI_PATTERN.search(text)
    if match:
        return _clean_doi(match.group(1))
    bare = _DOI_BARE.search(text)
    if bare:
        return _clean_doi(bare.group(1))
    return None


def _clean_doi(doi: str) -> str:
    """Strip trailing punctuation from a DOI."""
    return doi.rstrip(".,;:")


def extract_pmid(text: str) -> str | None:
    """Extract PubMed ID from reference text."""
    match = _PMID_PATTERN.search(text)
    if match:
        return match.group(1)
    return None


def extract_year(text: str) -> int | None:
    """Extract publication year from reference text."""
    matches = _YEAR_PATTERN.findall(text)
    for year_str in matches:
        year = int(year_str)
        if 1900 <= year <= 2030:
            return year
    return None


def parse_single_reference(ref_id: int, raw_text: str) -> Reference:
    """Parse a single raw reference string into a Reference model."""
    doi = extract_doi(raw_text)
    pmid = extract_pmid(raw_text)
    year = extract_year(raw_text)
    authors, title = parse_authors_title(raw_text)

    return Reference(
        id=ref_id,
        raw_text=raw_text.strip(),
        title=title,
        authors=authors,
        year=year,
        doi=doi,
        pmid=pmid,
    )


def split_reference_section(text: str) -> list[str]:
    """Split a reference section into individual reference strings.

    Handles multiple formats:
    1. Each reference on its own line with a number prefix
    2. Multi-line references (continuation lines without numbers)
    3. Paragraph-per-reference (one ref per line)
    """
    lines = text.strip().split("\n")
    refs: list[str] = []
    current: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _NUMBERED_REF.match(stripped):
            if current:
                refs.append(" ".join(current))
            current = [stripped]
        else:
            current.append(stripped)

    if current:
        refs.append(" ".join(current))

    if len(refs) >= 2:
        return refs

    # Fallback: treat each non-empty line as a separate reference
    logger.info(
        "Numbered splitting found %d refs; trying line-per-ref fallback",
        len(refs),
    )
    fallback = [
        ln.strip() for ln in lines
        if ln.strip() and len(ln.strip()) > 20
    ]
    if len(fallback) > len(refs):
        return fallback
    return refs
