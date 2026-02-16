"""Split compound citations into individual instances."""

import re

from refcheck.models.citation import CitationInstance
from refcheck.stages.detect_citations.numbered_detector import (
    expand_number_range,
)

_YEAR_RE = re.compile(r"\d{4}[a-z]?")


def split_compound_citation(
    citation: CitationInstance,
) -> list[CitationInstance]:
    """Split a compound citation into individual ones.

    Handles: semicolon-separated, multi-year, year suffixes, ranges.
    """
    if citation.style in ("numbered_bracket", "numbered_superscript"):
        return _split_numbered(citation)
    if citation.style in (
        "author_year_parenthetical", "author_year_narrative",
    ):
        return _split_author_year(citation)
    return [citation]


def _split_numbered(cit: CitationInstance) -> list[CitationInstance]:
    """Split [1,2,3] or [1-3] into individual number citations."""
    inner = cit.raw_marker.strip("[]")
    numbers = expand_number_range(inner)
    if len(numbers) <= 1:
        return [cit]
    results: list[CitationInstance] = []
    for num in numbers:
        results.append(cit.model_copy(update={
            "number": num,
            "raw_marker": f"[{num}]",
        }))
    return results


def _split_author_year(cit: CitationInstance) -> list[CitationInstance]:
    """Split author-year compound citations."""
    inner = cit.raw_marker
    if cit.style == "author_year_parenthetical":
        inner = inner.strip("()")

    # Split on semicolons first (separate author groups)
    groups = [g.strip() for g in re.split(r"\s*;\s*", inner)]
    if len(groups) > 1:
        return _split_semicolon_groups(cit, groups)

    # Same author, multiple years: "(Smith, 2020, 2021)"
    years = _YEAR_RE.findall(inner)
    if len(years) > 1:
        return _split_multi_year(cit, years)

    return [cit]


def _split_semicolon_groups(
    cit: CitationInstance, groups: list[str],
) -> list[CitationInstance]:
    """Split semicolon-separated author groups."""
    results: list[CitationInstance] = []
    for group in groups:
        # Remove prefixes like "see", "e.g.,"
        cleaned = re.sub(
            r"^(?:see|e\.g\.,?\s*|cf\.\s*|reviewed\s+in\s+)\s*",
            "", group, flags=re.I,
        )
        authors = _extract_group_authors(cleaned)
        years = _YEAR_RE.findall(cleaned)
        # If same author has multiple years, split further
        for year in (years or [None]):
            marker = f"({cleaned})" if cit.style == "author_year_parenthetical" else cleaned
            results.append(cit.model_copy(update={
                "raw_marker": marker,
                "authors": authors,
                "year": year,
            }))
    return results if results else [cit]


def _split_multi_year(
    cit: CitationInstance, years: list[str],
) -> list[CitationInstance]:
    """Split same-author multi-year: (Smith, 2020, 2021)."""
    results: list[CitationInstance] = []
    for year in years:
        authors = cit.authors
        if cit.style == "author_year_parenthetical":
            marker = f"({', '.join(authors)}, {year})"
        else:
            marker = f"{', '.join(authors)} ({year})"
        results.append(cit.model_copy(update={
            "raw_marker": marker,
            "year": year,
        }))
    return results


def _extract_group_authors(text: str) -> list[str]:
    """Extract author names from a group text (before the year)."""
    parts = re.split(r",?\s*\d{4}", text, maxsplit=1)
    auth_text = parts[0] if parts else text
    auth_text = re.sub(r"\s+et\s+al\.?", "", auth_text).strip()
    names = re.split(r"\s+(?:and|&)\s+|,\s*", auth_text)
    return [n.strip() for n in names if n.strip() and n[0:1].isupper()]
