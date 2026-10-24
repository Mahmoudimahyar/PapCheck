"""Extract and parse individual references from the reference section."""

import logging
import re

from refcheck.models.reference import Reference
from refcheck.stages.parse_docx.author_parser import parse_authors_title
from refcheck.stages.parse_docx.reference_repairer import (
    repair_reference_list,
    summarize_repairs,
)
from refcheck.stages.parse_docx.year_parser import extract_year_info

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
    """Extract publication year from reference text ("(2018b)" -> 2018)."""
    return extract_year_info(text).year


def parse_single_reference(
    ref_id: int,
    raw_text: str,
    raw_text_original: str = "",
    repair_applied: str = "none",
) -> Reference:
    """Parse a single raw reference string into a Reference model."""
    doi = extract_doi(raw_text)
    pmid = extract_pmid(raw_text)
    year_info = extract_year_info(raw_text)
    authors, title = parse_authors_title(raw_text)

    return Reference(
        id=ref_id,
        raw_text=raw_text.strip(),
        raw_text_original=raw_text_original or raw_text.strip(),
        repair_applied=repair_applied,
        title=title,
        authors=authors,
        year=year_info.year,
        year_suffix=year_info.suffix,
        doi=doi,
        pmid=pmid,
    )


def parse_references_with_repair(raw_entries: list[str]) -> list[Reference]:
    """Parse raw reference entries with repair pass applied first."""
    repaired = repair_reference_list(raw_entries)
    logger.info(summarize_repairs(repaired))

    refs: list[Reference] = []
    for idx, entry in enumerate(repaired, start=1):
        ref = parse_single_reference(
            ref_id=idx,
            raw_text=entry.text,
            raw_text_original=entry.text if entry.repair_type == "none" else "",
            repair_applied=entry.repair_type,
        )
        refs.append(ref)

    # Second pass: detect and fix bad titles via heuristics
    from refcheck.stages.parse_docx.title_repairer import (
        detect_and_repair_bad_titles,
    )

    needs_llm = detect_and_repair_bad_titles(refs)
    if needs_llm:
        logger.info("%d titles need LLM repair", len(needs_llm))

    return refs


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
