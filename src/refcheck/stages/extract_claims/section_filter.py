"""Filter manuscript sections for claim extraction eligibility."""

import re

from refcheck.models.reference import ManuscriptSection

# Headings that are NOT body text — skip these for claim extraction
_SKIP_HEADINGS = re.compile(
    r"^\s*(references|bibliography|works\s+cited|literature\s+cited"
    r"|acknowledgment|acknowledgement|acknowledgments|acknowledgements"
    r"|appendix|supplementary|conflicts?\s+of\s+interest"
    r"|funding|author\s+contributions|data\s+availability)\s*$",
    re.IGNORECASE,
)


def section_has_citations(text: str) -> bool:
    """Check if section text contains citation markers in any format.

    Detects: [1], [1-3], (1), (1,2), superscript-like numbers after
    sentences, and author-year citations like (Smith, 2020).
    """
    # Square brackets: [1], [1-3, 5]
    if re.search(r"\[\d+", text):
        return True
    # Parenthetical numbers: (1), (1-3), (1, 2)
    if re.search(r"\(\d{1,3}(?:\s*[-–,]\s*\d{1,3})*\)", text):
        return True
    # Author-year: (Smith, 2020), (Smith et al., 2020)
    if re.search(
        r"\([A-Z][a-z]+(?:\s+et\s+al\.?)?,?\s*\d{4}\)", text,
    ):
        return True
    # Superscript-like: digit(s) immediately after period/word boundary
    # Pattern: word or period followed by 1-3 digit number, then space/comma
    return bool(re.search(r"[a-z\.)]\d{1,3}(?:[,\s]|$)", text))


def is_body_section(section: ManuscriptSection) -> bool:
    """Check if a section is likely body text (not references/appendix)."""
    if not section.heading:
        return True  # No heading = likely body text
    return not _SKIP_HEADINGS.match(section.heading)
