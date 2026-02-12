"""Post-hoc validation of LLM evidence quotes against source text."""

import logging

from pydantic import BaseModel
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

_DEFAULT_MIN_SIMILARITY = 0.85
_SLIDING_WINDOW_STEP = 50


class QuoteValidation(BaseModel):
    """Result of validating a single evidence quote."""

    quote: str
    found_in_source: bool
    best_match: str | None = None
    similarity: float = 0.0


def validate_quotes(
    evidence_quotes: list[str],
    source_text: str,
    min_similarity: float = _DEFAULT_MIN_SIMILARITY,
) -> list[QuoteValidation]:
    """Validate that evidence quotes actually appear in source text.

    Uses fuzzy matching to handle minor whitespace/formatting differences.
    Returns validation results for each quote.
    """
    if not source_text:
        return [
            QuoteValidation(quote=q, found_in_source=False)
            for q in evidence_quotes
        ]

    normalized_source = _normalize_whitespace(source_text)
    results: list[QuoteValidation] = []

    for quote in evidence_quotes:
        if not quote.strip():
            results.append(QuoteValidation(quote=quote, found_in_source=False))
            continue

        validation = _validate_single_quote(
            quote, normalized_source, min_similarity
        )
        results.append(validation)

    return results


def _validate_single_quote(
    quote: str,
    source_text: str,
    min_similarity: float,
) -> QuoteValidation:
    """Validate a single quote against source text."""
    normalized_quote = _normalize_whitespace(quote)

    # Try partial ratio first (handles substring matching well)
    partial_score = fuzz.partial_ratio(
        normalized_quote.lower(), source_text.lower()
    ) / 100.0

    if partial_score >= min_similarity:
        best_match = _find_best_match_window(normalized_quote, source_text)
        return QuoteValidation(
            quote=quote,
            found_in_source=True,
            best_match=best_match,
            similarity=partial_score,
        )

    # Try sliding window search for longer quotes
    best_sim, best_window = _sliding_window_search(
        normalized_quote, source_text
    )

    found = best_sim >= min_similarity
    return QuoteValidation(
        quote=quote,
        found_in_source=found,
        best_match=best_window if found else None,
        similarity=best_sim,
    )


def _find_best_match_window(quote: str, source: str) -> str:
    """Find the best matching window in source for a quote."""
    quote_len = len(quote)
    if quote_len >= len(source):
        return source

    best_score = 0.0
    best_window = source[:quote_len]

    for i in range(0, len(source) - quote_len + 1, _SLIDING_WINDOW_STEP):
        window = source[i : i + quote_len]
        score = fuzz.ratio(quote.lower(), window.lower()) / 100.0
        if score > best_score:
            best_score = score
            best_window = window

    return best_window


def _sliding_window_search(
    quote: str,
    source: str,
) -> tuple[float, str]:
    """Search source text with sliding window for best match."""
    quote_len = len(quote)
    if quote_len >= len(source):
        score = fuzz.ratio(quote.lower(), source.lower()) / 100.0
        return score, source

    best_score = 0.0
    best_window = ""

    for i in range(0, len(source) - quote_len + 1, _SLIDING_WINDOW_STEP):
        window = source[i : i + quote_len + 20]
        score = fuzz.ratio(quote.lower(), window.lower()) / 100.0
        if score > best_score:
            best_score = score
            best_window = window

    return best_score, best_window


def _normalize_whitespace(text: str) -> str:
    """Collapse multiple whitespace into single spaces."""
    return " ".join(text.split())
