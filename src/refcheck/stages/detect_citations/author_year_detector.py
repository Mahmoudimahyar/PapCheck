"""Detect author-year citations (parenthetical and narrative)."""

import re

from refcheck.models.citation import CitationInstance

# --- Author name building blocks ---
_PARTICLE_WORD = r"(?:de|van|von|del|der|den|di|da|la|le|el|al|bin|ibn|dos|das|zur|zum)"
_PARTICLE = r"(?:" + _PARTICLE_WORD + r"(?:\s+" + _PARTICLE_WORD + r")*[\s\-])?"
_NAME_CHAR = r"[A-Za-z\u00C0-\u024F\u0400-\u04FF'''\-]"
_SINGLE_NAME = _PARTICLE + r"[A-Z]" + _NAME_CHAR + r"+"
_ET_AL = r"(?:\s+et\s+al\.?)"

# --- Year building blocks ---
_YEAR = r"(?:\d{4}[a-z]?|n\.d\.)"
_YEAR_LIST = _YEAR + r"(?:\s*,\s*" + _YEAR + r")*"

# --- Parenthetical patterns ---
_TWO_AUTH = _SINGLE_NAME + r"\s+(?:and|&)\s+" + _SINGLE_NAME
_AUTHOR_GROUP = (
    r"(?:" + _TWO_AUTH + r"|" + _SINGLE_NAME + r")" + _ET_AL + r"?"
)
_PREFIX = r"(?:(?:see\s+|e\.g\.,?\s*|cf\.\s*|reviewed\s+in\s+|as\s+reviewed\s+by\s+))"
_SINGLE_CIT = r"(?:" + _PREFIX + r"?" + _AUTHOR_GROUP + r",?\s+" + _YEAR_LIST + r")"
_COMPOUND = _SINGLE_CIT + r"(?:\s*;\s*" + _SINGLE_CIT + r")*"
_PAREN_FULL = re.compile(r"\(" + _COMPOUND + r"\)")

# --- False positive filters ---
_FALSE_POS = [
    re.compile(r"^\((?:n|N)\s*[=<>≤≥]"),
    re.compile(r"^\((?:p|P)\s*[=<>≤≥]"),
    re.compile(r"^\((?:Fig(?:ure)?|Table|Supplementary|Eq(?:uation)?)\s", re.I),
    re.compile(r"^\((?:i\.e\.|e\.g\.)[,\s]+(?!.*\d{4})"),
    re.compile(r"^\([A-Z]{2,}\)$"),
    re.compile(r"^\(\d+\.?\d*\s*(?:kDa|mg|mL|[μµ][gLm]|nm|mm|cm|°C|kg|%)\)"),
    re.compile(r"^\((?:see\s+)?(?:Methods|Section|Appendix|Chapter)\b", re.I),
]

# --- Narrative patterns ---
_NON_AUTHOR = frozenset({
    "table", "figure", "fig", "university", "section", "chapter",
    "equation", "protocol", "method", "phase", "stage", "step",
    "group", "type", "grade", "class", "level", "form", "part",
    "volume", "issue", "scheme", "chart", "box", "panel",
    "supplementary", "appendix", "however", "therefore", "thus",
    "although", "because", "since", "while", "where", "when",
    "each", "both", "after", "before", "during", "between",
})

_NARR_YEAR = re.compile(
    r"(" + _AUTHOR_GROUP + r")\s+\((" + _YEAR_LIST + r")\)",
)


def detect_author_year_parenthetical(
    text: str, para_idx: int, section: str,
) -> list[CitationInstance]:
    """Detect all (Author et al., YEAR) style citations."""
    results: list[CitationInstance] = []
    for m in _PAREN_FULL.finditer(text):
        raw = m.group(0)
        if _is_false_positive(raw):
            continue
        results.append(CitationInstance(
            raw_marker=raw,
            style="author_year_parenthetical",
            paragraph_index=para_idx,
            char_start=m.start(),
            char_end=m.end(),
            section_heading=section,
            authors=_extract_authors(raw),
            year=_extract_first_year(raw),
        ))
    return results


def detect_author_year_narrative(
    text: str, para_idx: int, section: str,
) -> list[CitationInstance]:
    """Detect Author et al. (YEAR) style narrative citations."""
    results: list[CitationInstance] = []
    for m in _NARR_YEAR.finditer(text):
        author_part = m.group(1)
        # Filter non-author words
        first_word = author_part.split()[0].rstrip(",").lower()
        if first_word in _NON_AUTHOR:
            continue
        raw = m.group(0)
        results.append(CitationInstance(
            raw_marker=raw,
            style="author_year_narrative",
            paragraph_index=para_idx,
            char_start=m.start(),
            char_end=m.end(),
            section_heading=section,
            authors=_extract_authors_from_group(author_part),
            year=_extract_first_year(raw),
            is_narrative=True,
        ))
    return results


def _is_false_positive(raw: str) -> bool:
    """Check if a parenthetical match is actually a non-citation."""
    return any(p.search(raw) for p in _FALSE_POS)


def _extract_authors(raw: str) -> list[str]:
    """Extract author last names from a parenthetical citation."""
    # Remove outer parens and prefix
    inner = raw.strip("()")
    inner = re.sub(
        r"^(?:see|e\.g\.,?\s*|cf\.\s*|reviewed\s+in\s+"
        r"|as\s+reviewed\s+by\s+)\s*", "", inner, flags=re.I,
    )
    # Take only text before the first year
    parts = re.split(r",?\s*\d{4}", inner, maxsplit=1)
    auth_text = parts[0] if parts else inner
    return _extract_authors_from_group(auth_text)


def _extract_authors_from_group(text: str) -> list[str]:
    """Extract author last names from an author group string."""
    # Remove 'et al.'
    cleaned = re.sub(r"\s+et\s+al\.?", "", text).strip()
    # Split on 'and', '&', or ','
    parts = re.split(r"\s+(?:and|&)\s+|,\s*", cleaned)
    authors: list[str] = []
    for p in parts:
        p = p.strip()
        if p and p[0:1].isupper():
            authors.append(p)
    return authors


def _extract_first_year(text: str) -> str | None:
    """Extract the first year from citation text."""
    if "n.d." in text:
        return None
    m = re.search(r"\d{4}[a-z]?", text)
    return m.group(0) if m else None
