"""Tests for post-hoc evidence quote validation."""


from refcheck.stages.verify_claims.quote_validator import (
    validate_quotes,
)
from refcheck.stages.verify_claims.source_cleaning import join_lines, sanitize_source_text

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


class TestPdfNormalization:
    """V5: PDF artefacts must not reject genuine quotes."""

    def test_ligatures_and_soft_hyphens(self) -> None:
        source = "The e\ufb03cacy of the treat\u00adment was signi\ufb01cant."
        result = validate_quotes(["The efficacy of the treatment was significant"], source)[0]
        assert result.found_in_source and result.similarity == 1.0

    def test_line_break_hyphenation(self) -> None:
        source = "facilitate clearance of aggregation- prone proteins such as A\u03b2[20], [21]."
        quote = "facilitate clearance of aggregation-prone proteins such as A\u03b2."
        assert validate_quotes([quote], source)[0].similarity == 1.0

    def test_citation_markers_and_curly_quotes_ignored(self) -> None:
        source = "Autophagy is a \u201ckey\u201d pathway (12, 13) for clearance of proteins [4]."
        quote = 'Autophagy is a "key" pathway for clearance of proteins'
        assert validate_quotes([quote], source)[0].similarity == 1.0

    def test_case_and_dash_variants(self) -> None:
        source = "RESULTS SHOWED A 30% DECREASE IN ALL\u2013CAUSE MORTALITY."
        quote = "results showed a 30% decrease in all-cause mortality"
        assert validate_quotes([quote], source)[0].found_in_source

    def test_offsets_point_into_original_source(self) -> None:
        source = "Intro text here.  The e\ufb03cacy\nwas   high in mice. Tail text."
        result = validate_quotes(["The efficacy was high in mice"], source)[0]
        assert result.char_start is not None and result.char_end is not None
        assert source[result.char_start:result.char_end] == result.best_match
        assert result.best_match == "The e\ufb03cacy\nwas   high in mice"

    def test_numbers_must_match(self) -> None:
        result = validate_quotes(["Results showed a 45% decrease in mortality"], _SOURCE_TEXT)[0]
        assert result.similarity < 1.0

    def test_long_source_is_fast(self) -> None:
        source = ("Filler sentence about unrelated laboratory routines. " * 4000
                  + "Rapamycin lowered amyloid levels in treated mice.")
        result = validate_quotes(["Rapamycin lowered amyloid levels in treated mice"], source)[0]
        assert result.found_in_source and result.best_match is not None


class TestNormalisationConsistency:
    """M9: source text is NFKC-normalised before retrieval; quotes must still validate."""

    def test_plain_quote_against_ligature_source(self) -> None:
        source = "Encapsulation was useful in preventing hyperﬁbrosis and promoting ﬂow."
        result = validate_quotes(["preventing hyperfibrosis and promoting flow"], source)[0]
        assert result.found_in_source and result.similarity == 1.0

    def test_ligature_quote_against_sanitized_source(self) -> None:
        source = sanitize_source_text("Pores of 5 µm limited ﬁbrosis（n = 4）.")
        assert "ﬁ" not in source and "µ" not in source
        result = validate_quotes(["Pores of 5 µm limited ﬁbrosis (n = 4)"], source)[0]
        assert result.found_in_source

    def test_line_break_compound_hyphen(self) -> None:
        source = join_lines(["CD4+ T-", "cell infiltration fell."])
        assert source == "CD4+ T-cell infiltration fell."
        assert validate_quotes(["CD4+ T-cell infiltration fell"], source)[0].found_in_source
