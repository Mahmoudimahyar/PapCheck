"""Unit tests for citation_detector module."""

from refcheck.stages.parse_docx.citation_detector import (
    detect_citation_style,
    expand_citation_range,
    find_citations_in_text,
)


class TestExpandCitationRange:
    def test_single_number(self) -> None:
        assert expand_citation_range("3") == [3]

    def test_simple_range(self) -> None:
        assert expand_citation_range("1-5") == [1, 2, 3, 4, 5]

    def test_range_with_singles(self) -> None:
        result = expand_citation_range("1-5, 7")
        assert result == [1, 2, 3, 4, 5, 7]

    def test_multiple_ranges(self) -> None:
        result = expand_citation_range("1-3, 5, 7-9")
        assert result == [1, 2, 3, 5, 7, 8, 9]

    def test_en_dash(self) -> None:
        result = expand_citation_range("1\u20135")
        assert result == [1, 2, 3, 4, 5]

    def test_comma_separated(self) -> None:
        result = expand_citation_range("1, 3, 5")
        assert result == [1, 3, 5]


class TestDetectCitationStyle:
    def test_numbered_style(self) -> None:
        text = "Results show [1] that treatment [2] is effective [3]."
        assert detect_citation_style(text) == "numbered"

    def test_author_year_style(self) -> None:
        text = (
            "Results show (Smith, 2020) that treatment "
            "(Jones, 2019) is effective (Lee, 2021)."
        )
        assert detect_citation_style(text) == "author_year"

    def test_unknown_style(self) -> None:
        text = "No citations at all in this text."
        assert detect_citation_style(text) == "unknown"


class TestFindCitationsInText:
    def test_find_numbered(self) -> None:
        text = "Results [1] show that [2, 3] treatment works."
        citations = find_citations_in_text(text)
        assert len(citations) == 2
        assert citations[0].reference_ids == [1]
        assert citations[1].reference_ids == [2, 3]

    def test_find_range(self) -> None:
        text = "Multiple studies [1-5, 7] agree on this."
        citations = find_citations_in_text(text)
        assert len(citations) == 1
        assert citations[0].reference_ids == [1, 2, 3, 4, 5, 7]

    def test_position_tracking(self) -> None:
        text = "First [1] then [2]."
        citations = find_citations_in_text(text)
        assert citations[0].position < citations[1].position

    def test_no_citations(self) -> None:
        text = "Plain text without any citations."
        citations = find_citations_in_text(text)
        assert len(citations) == 0
