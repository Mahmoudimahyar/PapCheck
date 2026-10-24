"""Build structured EvidenceSection objects from verification data."""

import logging
import re
from typing import Literal

from rapidfuzz import fuzz

from refcheck.models.evidence import EvidenceSection, QuoteHighlight

MatchType = Literal["direct", "paraphrased", "numeric_mismatch", "absent"]

logger = logging.getLogger(__name__)

_DIRECT_THRESHOLD = 0.95
_PARAPHRASED_THRESHOLD = 0.75
_MATCH_THRESHOLD = 0.60
_NUMBER_PATTERN = re.compile(r"\d+\.?\d*%?")


def build_evidence_sections(
    source_sections: list[str],
    source_headings: list[str],
    evidence_quotes: list[str],
    source_text: str,
    claim_text: str,
) -> list[EvidenceSection]:
    """Build EvidenceSection objects with positioned quote highlights.

    Takes the raw source sections (from section_finder) and the LLM's
    evidence quotes, then locates quotes within sections and classifies
    match types.
    """
    sections: list[EvidenceSection] = []

    for i, section_text in enumerate(source_sections):
        heading = source_headings[i] if i < len(source_headings) else ""
        highlights = _find_quotes_in_section(
            section_text, evidence_quotes, claim_text,
        )
        sections.append(EvidenceSection(
            section_heading=heading,
            full_text=section_text,
            quote_highlights=highlights,
        ))

    return sections


def _find_quotes_in_section(
    section_text: str,
    evidence_quotes: list[str],
    claim_text: str,
) -> list[QuoteHighlight]:
    """Locate evidence quotes within a section, classify match types."""
    highlights: list[QuoteHighlight] = []
    for quote in evidence_quotes:
        if not quote.strip():
            continue
        result = _locate_quote(quote, section_text, claim_text)
        if result is not None:
            highlights.append(result)
    return highlights


def _locate_quote(
    quote: str, section_text: str, claim_text: str,
) -> QuoteHighlight | None:
    """Find a quote within section text and classify match type."""
    if not section_text:
        return None

    # Try exact substring first
    pos = section_text.find(quote)
    if pos != -1:
        match_type = classify_match(quote, quote, claim_text, 1.0)
        return QuoteHighlight(
            quote=quote, char_start=pos,
            char_end=pos + len(quote), match_type=match_type,
        )

    best_pos, best_end, best_score = _best_alignment(quote, section_text)
    if best_score >= _MATCH_THRESHOLD and best_end > best_pos:
        best_text = section_text[best_pos:best_end]
        match_type = classify_match(quote, best_text, claim_text, best_score)
        return QuoteHighlight(
            quote=quote, char_start=best_pos,
            char_end=best_end, match_type=match_type,
        )

    return None


def _best_alignment(query: str, text: str) -> tuple[int, int, float]:
    """Best fuzzy placement of query in text: (start, end, similarity 0-1).

    rapidfuzz's partial_ratio_alignment replaces the old per-character
    sliding window (O(len(text)) ratio calls per quote).
    """
    # Lowercasing is only safe for offsets when it preserves string length.
    q_low, t_low = query.lower(), text.lower()
    if len(q_low) == len(query) and len(t_low) == len(text):
        query, text = q_low, t_low
    alignment = fuzz.partial_ratio_alignment(query, text)
    if alignment is None:
        return 0, 0, 0.0
    start = max(0, min(alignment.dest_start, len(text)))
    end = max(start, min(alignment.dest_end, len(text)))
    start, end = snap_to_words(text, start, end)
    return start, end, alignment.score / 100.0


def snap_to_words(text: str, start: int, end: int) -> tuple[int, int]:
    """Widen [start, end) so it does not cut a word in half (alignment windows
    have the quote's length, so paraphrases can land mid-word)."""
    while 0 < start < len(text) and text[start - 1].isalnum() and text[start].isalnum():
        start -= 1
    while 0 < end < len(text) and text[end - 1].isalnum() and text[end].isalnum():
        end += 1
    return start, end


def classify_match(
    quote: str, matched_text: str, claim_text: str, similarity: float,
) -> MatchType:
    """Classify the match type between quote and matched text.

    Always checks for numeric mismatch between claim and source, even
    if the quote itself is an exact match — the claim may overstate a number.
    """
    claim_numbers = extract_numbers(claim_text)
    source_numbers = extract_numbers(matched_text)
    if claim_numbers and source_numbers and claim_numbers != source_numbers:
        return "numeric_mismatch"

    if similarity >= _DIRECT_THRESHOLD:
        return "direct"

    if similarity >= _PARAPHRASED_THRESHOLD:
        return "paraphrased"

    return "absent"


def extract_numbers(text: str) -> set[str]:
    """Extract all numbers (integers, decimals, percentages) from text."""
    return set(_NUMBER_PATTERN.findall(text))
