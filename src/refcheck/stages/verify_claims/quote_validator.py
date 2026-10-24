"""Post-hoc validation of LLM evidence quotes against source text.

Both sides are normalised before fuzzy matching so PDF artefacts do not reject
genuine quotes: case, whitespace, ligatures (ﬁ→fi), soft hyphens, dash and
quote variants, line-break hyphenation ("aggre- gation" ≈ "aggregation") and
numeric citation markers ("[12]", "(3, 4)"). `best_match` and the offsets
refer to the ORIGINAL source text.
"""

import logging
import re
import unicodedata

from pydantic import BaseModel
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

DEFAULT_MIN_SIMILARITY = 0.85  # fuzzy (partial_ratio); 1.0 = exact
_CITATION_RE = re.compile(
    r"\[\s*\d+(?:\s*[-–,;]\s*\d+)*\s*\]|\(\s*\d+(?:\s*[-–,;]\s*\d+)*\s*\)"
)
_CHAR_MAP = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "″": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
    "―": "-", "−": "-", " ": " ",
}
_DROP_CHARS = frozenset("­​‌‍⁠﻿")


class QuoteValidation(BaseModel):
    """Result of validating a single evidence quote."""

    quote: str
    found_in_source: bool
    best_match: str | None = None
    similarity: float = 0.0
    char_start: int | None = None  # offsets of best_match in the original source
    char_end: int | None = None


def normalize_for_match(text: str) -> tuple[str, list[int]]:
    """Comparison form of text plus, per output char, its index in the input.

    Lowercased, NFKC (ligatures), unified quotes/dashes, citation markers and
    soft hyphens removed, hyphens dropped together with following whitespace,
    and whitespace collapsed.
    """
    skip = [False] * len(text)
    for match in _CITATION_RE.finditer(text):
        for i in range(match.start(), match.end()):
            skip[i] = True
    out: list[str] = []
    index: list[int] = []
    after_hyphen = False
    for i, raw in enumerate(text):
        if skip[i] or raw in _DROP_CHARS:
            continue
        mapped = raw if raw < "\x80" else unicodedata.normalize("NFKC", _CHAR_MAP.get(raw, raw))
        for ch in mapped.lower():
            if ch == "-":
                after_hyphen = True
                continue
            if ch.isspace():
                if after_hyphen or not out or out[-1] == " ":
                    continue
                ch = " "
            after_hyphen = False
            out.append(ch)
            index.append(i)
    while out and out[-1] == " ":
        out.pop()
        index.pop()
    return "".join(out), index


def validate_quotes(
    evidence_quotes: list[str],
    source_text: str,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
) -> list[QuoteValidation]:
    """Validate that evidence quotes actually appear in source text (fuzzy, normalised)."""
    if not source_text:
        return [QuoteValidation(quote=q, found_in_source=False) for q in evidence_quotes]
    norm_source, index = normalize_for_match(source_text)
    return [
        _validate_single_quote(quote, source_text, norm_source, index, min_similarity)
        for quote in evidence_quotes
    ]


def _validate_single_quote(
    quote: str,
    source_text: str,
    norm_source: str,
    index: list[int],
    min_similarity: float,
) -> QuoteValidation:
    norm_quote, _ = normalize_for_match(quote.strip().strip("\"'“”…."))
    if not norm_quote or not norm_source:
        return QuoteValidation(quote=quote, found_in_source=False)
    if len(norm_quote) > len(norm_source):
        similarity = fuzz.ratio(norm_quote, norm_source) / 100.0
        start, end = 0, len(norm_source)
    else:
        pos = norm_source.find(norm_quote)
        if pos >= 0:
            similarity, start, end = 1.0, pos, pos + len(norm_quote)
        else:
            alignment = fuzz.partial_ratio_alignment(norm_quote, norm_source)
            if alignment is None:
                return QuoteValidation(quote=quote, found_in_source=False)
            similarity = alignment.score / 100.0
            start, end = alignment.dest_start, alignment.dest_end
    found = similarity >= min_similarity
    char_start, char_end = _original_span(index, start, end)
    char_start, char_end = _snap_to_words(source_text, char_start, char_end)
    best = source_text[char_start:char_end] if found and char_end > char_start else None
    return QuoteValidation(
        quote=quote,
        found_in_source=found,
        best_match=best,
        similarity=similarity,
        char_start=char_start if found else None,
        char_end=char_end if found else None,
    )


def _snap_to_words(text: str, start: int, end: int) -> tuple[int, int]:
    # Fixed-length alignment windows can start or stop mid-word on paraphrases.
    while 0 < start < len(text) and text[start - 1].isalnum() and text[start].isalnum():
        start -= 1
    while 0 < end < len(text) and text[end - 1].isalnum() and text[end].isalnum():
        end += 1
    return start, end


def _original_span(index: list[int], start: int, end: int) -> tuple[int, int]:
    if not index or end <= start:
        return 0, 0
    start = min(max(start, 0), len(index) - 1)
    end = min(max(end, start + 1), len(index))
    return index[start], index[end - 1] + 1
