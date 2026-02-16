"""Sentence boundary detection for citation context extraction."""

import re

# Abbreviations that should NOT cause sentence splits
_ABBREVS = [
    "et al", "e.g", "i.e", "vs", "approx", "ca", "viz",
    "Fig", "Figs", "Ref", "Refs", "Dr", "Prof", "Jr", "Sr",
    "Mr", "Mrs", "Ms", "St", "Inc", "Ltd", "Corp", "Vol",
    "No", "Dept", "Univ", "Assoc", "Natl", "Intl",
    "J", "Biol", "Chem", "Sci", "Med", "Eng", "Phys",
    "Pharmacol", "Physiol", "Rev", "Res", "Ther",
    "Lett", "Proc", "Soc", "Am", "Eur", "Int",
    "Mol", "Cell", "Biochem", "Biophys", "Genet",
    "Immunol", "Neurosci", "Oncol", "Pathol",
]

_PLACEHOLDER = "\u2020"  # dagger symbol as placeholder


def extract_sentence_context(
    text: str,
    citation_start: int,
    citation_end: int,
) -> tuple[str, int, int]:
    """Find the sentence containing the citation.

    Returns (sentence_text, sentence_start, sentence_end).
    Handles abbreviations, decimals, and initials correctly.
    """
    protected, replacements = _protect_abbreviations(text)
    boundaries = _find_sentence_boundaries(protected)

    # Find which sentence contains the citation
    for start, end in boundaries:
        if start <= citation_start < end:
            sentence = text[start:end].strip()
            return sentence, start, end

    # Fallback: return the whole paragraph
    return text.strip(), 0, len(text)


def _protect_abbreviations(text: str) -> tuple[str, list[tuple[int, str]]]:
    """Replace abbreviation dots with placeholders."""
    result = text
    replacements: list[tuple[int, str]] = []

    # Protect known abbreviations
    for abbr in _ABBREVS:
        pattern = re.compile(re.escape(abbr) + r"\.", re.IGNORECASE)
        result = pattern.sub(
            lambda m: m.group(0).replace(".", _PLACEHOLDER), result,
        )

    # Protect decimals: 3.5, 0.001, p = 0.05
    result = re.sub(
        r"(\d)\.(\d)",
        lambda m: m.group(1) + _PLACEHOLDER + m.group(2),
        result,
    )

    # Protect initials: J. A. Smith (single letter + period + space + period)
    # Only protect when preceding another initial or part of "A. B. Name"
    result = re.sub(
        r"\b([A-Z])\.(?=\s*[A-Z]\.)",
        lambda m: m.group(1) + _PLACEHOLDER,
        result,
    )

    return result, replacements


def _find_sentence_boundaries(text: str) -> list[tuple[int, int]]:
    """Find sentence boundaries in protected text."""
    # Split on . ! ? followed by whitespace+uppercase (or end)
    boundaries: list[tuple[int, int]] = []
    pattern = re.compile(r"[.!?]+(?:\s+(?=[A-Z\(\[\"])|\s*$)")

    start = 0
    for m in pattern.finditer(text):
        end = m.end()
        boundaries.append((start, end))
        start = end

    # Add remaining text as last sentence
    if start < len(text):
        boundaries.append((start, len(text)))

    # Merge very short fragments (< 15 chars) with previous
    if len(boundaries) > 1:
        boundaries = _merge_short_fragments(boundaries, text)

    return boundaries


def _merge_short_fragments(
    bounds: list[tuple[int, int]], text: str,
) -> list[tuple[int, int]]:
    """Merge fragments shorter than 10 chars with previous sentence."""
    merged: list[tuple[int, int]] = [bounds[0]]
    for start, end in bounds[1:]:
        fragment = text[start:end].strip()
        if len(fragment) < 10 and merged:
            prev_start, _ = merged[-1]
            merged[-1] = (prev_start, end)
        else:
            merged.append((start, end))
    return merged
