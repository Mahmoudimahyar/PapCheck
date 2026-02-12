"""Tests for post-hoc evidence quote validation."""

import pytest

from refcheck.stages.verify_claims.quote_validator import (
    QuoteValidation,
    validate_quotes,
)

_SOURCE_TEXT = (
    "Drug X was associated with a significant reduction in mortality rates. "
    "The study enrolled 500 elderly patients (age > 65) from three hospitals. "
    "Results showed a 30% decrease in all-cause mortality (p < 0.001). "
    "Secondary outcomes included improved quality of life scores. "
    "The control group showed a 12% non-significant reduction (p = 0.08)."
)


class TestValidateQuotes:
    def test_exact_quote_found(self) -> None:
        """Exact quote from source returns high similarity."""
        quotes = ["Results showed a 30% decrease in all-cause mortality (p < 0.001)."]
        results = validate_quotes(quotes, _SOURCE_TEXT)
        assert len(results) == 1
        assert results[0].found_in_source is True
        assert results[0].similarity >= 0.95

    def test_whitespace_differences_still_found(self) -> None:
        """Quote with minor whitespace differences is still found."""
        quotes = ["Results  showed a 30% decrease  in all-cause mortality"]
        results = validate_quotes(quotes, _SOURCE_TEXT)
        assert len(results) == 1
        assert results[0].found_in_source is True

    def test_hallucinated_quote_not_found(self) -> None:
        """Completely made-up quote is not found in source."""
        quotes = ["We discovered that aspirin prevents all forms of cancer"]
        results = validate_quotes(quotes, _SOURCE_TEXT)
        assert len(results) == 1
        assert results[0].found_in_source is False
        assert results[0].similarity < 0.85

    def test_paraphrased_quote_partial_match(self) -> None:
        """Slightly paraphrased quote is still found via fuzzy matching."""
        # Close enough paraphrase to pass partial matching threshold
        quotes = ["showed a 30% decrease in all-cause mortality"]
        results = validate_quotes(quotes, _SOURCE_TEXT)
        assert len(results) == 1
        assert results[0].found_in_source is True
        assert results[0].similarity >= 0.85

    def test_empty_source_all_not_found(self) -> None:
        """Empty source text means all quotes not found."""
        quotes = ["any quote", "another quote"]
        results = validate_quotes(quotes, "")
        assert all(not r.found_in_source for r in results)

    def test_empty_quotes_list(self) -> None:
        """Empty quotes list returns empty results."""
        results = validate_quotes([], _SOURCE_TEXT)
        assert results == []

    def test_empty_quote_string(self) -> None:
        """Empty quote string is marked not found."""
        results = validate_quotes([""], _SOURCE_TEXT)
        assert len(results) == 1
        assert results[0].found_in_source is False

    def test_multiple_quotes_mixed_results(self) -> None:
        """Mix of valid and invalid quotes returns correct results."""
        quotes = [
            "The study enrolled 500 elderly patients",
            "Completely fabricated result about cats",
        ]
        results = validate_quotes(quotes, _SOURCE_TEXT)
        assert len(results) == 2
        assert results[0].found_in_source is True
        assert results[1].found_in_source is False

    def test_best_match_populated(self) -> None:
        """Validated quotes include best_match text."""
        quotes = ["Results showed a 30% decrease in all-cause mortality"]
        results = validate_quotes(quotes, _SOURCE_TEXT)
        assert results[0].found_in_source is True
        assert results[0].best_match is not None

    def test_custom_min_similarity(self) -> None:
        """Custom min_similarity threshold works."""
        quotes = ["Drug X reduced mortality"]
        # Very strict threshold
        strict = validate_quotes(quotes, _SOURCE_TEXT, min_similarity=0.99)
        # Lenient threshold
        lenient = validate_quotes(quotes, _SOURCE_TEXT, min_similarity=0.5)

        # Lenient should find it more easily
        assert lenient[0].similarity >= strict[0].similarity
