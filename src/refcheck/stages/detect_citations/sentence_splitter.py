"""Sentence boundary detection for citation context extraction."""

import re

from refcheck.stages.detect_citations.citation_only import (
    is_citation_only,
    is_narrative_only,
)
from refcheck.stages.detect_citations.verb_heuristics import opens_with_predicate

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

    # Protect known abbreviations. "et al." is often typed with a no-break or
    # narrow no-break space ("et al."): any whitespace must match, or the
    # sentence is cut after "al." and the claim becomes a fragment.
    for abbr in _ABBREVS:
        escaped = re.escape(abbr).replace(r"\ ", r"\s+")
        pattern = re.compile(r"\b" + escaped + r"\.", re.IGNORECASE)
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
    # Split on . ! ? followed by whitespace+uppercase (or end). Sentences may
    # also start with a lowercase term that has capitals inside ("pH-responsive",
    # "siRNA", "mRNA"); missing those merged two sentences into one claim.
    boundaries: list[tuple[int, int]] = []
    pattern = re.compile(
        r"[.!?]+(?:\s+(?=[A-Z\(\[\"]|[a-z]{1,3}[A-Z])|\s*$)",
    )

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


_CITATION_ONLY = re.compile(
    r"\([^()]*\d{4}[a-z]?[^()]*\)|\[\s*\d[\d,\s\-–—]*\]",
)
# A sentence opening on the cited authors or their study ("They used ...")
_BACK_REFERENCE = re.compile(
    r"\s*(?:They|Their|Th(?:e|ese)\s+(?:authors|investigators)"
    r"|Th(?:is|at)\s+(?:study|work|trial|group|team|paper|report)"
    r"|In\s+(?:this|that|their)\s+(?:study|work|trial|paper|report))\b",
)


def _content_length(fragment: str) -> int:
    """Length of a fragment once citation markers and punctuation are removed.

    A fragment such as "(Wade et al., 2020; Bento et al., 2025)." that
    follows a sentence-final period carries no assertion of its own; it
    belongs to the preceding sentence.
    """
    stripped = _CITATION_ONLY.sub("", fragment)
    return len(re.sub(r"[\s.;,:!?]+", "", stripped))


def _merge_short_fragments(
    bounds: list[tuple[int, int]], text: str,
) -> list[tuple[int, int]]:
    """Merge short or citation-only fragments into a neighbouring sentence.

    A citation-only fragment normally closes the previous sentence ("...
    grafts. (Lee, 2020)."). A narrative one followed by a sentence with no
    subject ("Lee et al. (2002). Used X in mice ...") is that sentence's
    subject cut off by a stray period, so it joins the next sentence, as it
    does before one about the cited authors ("... (2002). They used X ...").
    """
    merged: list[tuple[int, int]] = []
    carried: int | None = None  # start of a fragment joining the next sentence
    for i, (start, end) in enumerate(bounds):
        if carried is not None:
            start, carried = carried, None
        fragment = text[start:end].strip()
        if _joins_next(text, bounds, i, fragment):
            carried = start
        elif merged and _is_fragment(fragment):
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def _is_fragment(fragment: str) -> bool:
    """Too short, or nothing but parenthetical / numbered markers, to stand as a
    sentence. A narrative one ("Vandermeer et al. (2002).") not joining the next
    sentence keeps only the length rule: pulled into the previous sentence, its
    reference would be verified against that sentence's unrelated claim."""
    return (
        len(fragment) < 10 or _content_length(fragment) < 10
        or (is_citation_only(fragment) and not is_narrative_only(fragment))
    )


def _joins_next(
    text: str, bounds: list[tuple[int, int]], i: int, fragment: str,
) -> bool:
    """A narrative citation-only fragment whose next sentence (same line) has
    no subject of its own ("Lee et al. (2002). Used X ...") or opens on the
    cited authors ("Lee et al. (2002). They used X ...")."""
    if i + 1 >= len(bounds) or not is_narrative_only(fragment):
        return False
    start, end = bounds[i]
    if "\n" in text[start:end]:
        return False
    next_start, next_end = bounds[i + 1]
    following = text[next_start:next_end]
    return opens_with_predicate(following) or bool(_BACK_REFERENCE.match(following))
