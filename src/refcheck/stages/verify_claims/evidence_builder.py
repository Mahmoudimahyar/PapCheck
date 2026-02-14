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

    # Fuzzy sliding window search
    best_pos, best_end, best_score, best_text = _sliding_window_search(
        quote, section_text,
    )
    if best_score >= _MATCH_THRESHOLD:
        match_type = classify_match(quote, best_text, claim_text, best_score)
        return QuoteHighlight(
            quote=quote, char_start=best_pos,
            char_end=best_end, match_type=match_type,
        )

    return None


def _sliding_window_search(
    query: str, text: str,
) -> tuple[int, int, float, str]:
    """Search for query in text with a sliding window."""
    window = len(query)
    best_pos = 0
    best_score = 0.0
    for i in range(max(1, len(text) - window + 1)):
        chunk = text[i:i + window]
        score = fuzz.ratio(query, chunk) / 100.0
        if score > best_score:
            best_score = score
            best_pos = i

    end = min(best_pos + window, len(text))
    matched_text = text[best_pos:end]
    return best_pos, end, best_score, matched_text


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
