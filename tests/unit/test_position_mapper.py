"""Tests for claim position mapping to manuscript locations."""

from refcheck.models.claim import Claim
from refcheck.models.reference import ManuscriptSection, ParsedManuscript
from refcheck.stages.extract_claims.position_mapper import map_claims_to_positions


def _make_manuscript(sections: list[tuple[str, str]]) -> ParsedManuscript:
    """Build a ParsedManuscript from (heading, text) pairs."""
    return ParsedManuscript(
        filename="test.docx",
        sections=[
            ManuscriptSection(heading=h, text=t) for h, t in sections
        ],
    )


def _make_claim(claim_id: int, text: str) -> Claim:
    """Build a minimal claim with manuscript_text."""
    return Claim(id=claim_id, manuscript_text=text, extracted_claim=text)


class TestPositionMapper:
    def test_exact_match_correct_offsets(self) -> None:
        """PM-01: Exact text match returns correct paragraph/char offsets."""
        ms = _make_manuscript([
            ("Introduction", "Background information here."),
            ("Results", "Drug X reduced mortality by 30% in elderly patients [7]."),
        ])
        claim = _make_claim(1, "Drug X reduced mortality by 30%")
        results = map_claims_to_positions([claim], ms)

        assert len(results) == 1
        loc = results[0].location
        assert loc is not None
        assert loc.paragraph_index == 1
        assert loc.char_start == 0
        assert loc.char_end == 31
        assert loc.section_heading == "Results"

    def test_citation_markers_extracted(self) -> None:
        """PM-02: Citation markers like [7, 8] are captured."""
        ms = _make_manuscript([
            ("Results", "Drug X reduced mortality [7, 8] in patients."),
        ])
        claim = _make_claim(1, "Drug X reduced mortality [7, 8]")
        results = map_claims_to_positions([claim], ms)

        loc = results[0].location
        assert loc is not None
        assert "7, 8" in loc.citation_markers

    def test_fuzzy_match_finds_closest(self) -> None:
        """PM-03: Fuzzy match works when exact match fails."""
        ms = _make_manuscript([
            ("Results", "Drug X reduced all-cause mortality by 30% in elderly patients."),
        ])
        # Slightly different wording than manuscript
        claim = _make_claim(1, "Drug X reduced mortality by 30% in elderly patients")
        results = map_claims_to_positions([claim], ms)

        loc = results[0].location
        assert loc is not None
        assert loc.paragraph_index == 0

    def test_two_claims_same_paragraph(self) -> None:
        """PM-04: Two claims in same paragraph map with different offsets."""
        text = "Drug X reduced mortality [7] and improved quality of life [12]."
        ms = _make_manuscript([("Results", text)])

        c1 = _make_claim(1, "Drug X reduced mortality [7]")
        c2 = _make_claim(2, "improved quality of life [12]")
        results = map_claims_to_positions([c1, c2], ms)

        loc1 = results[0].location
        loc2 = results[1].location
        assert loc1 is not None
        assert loc2 is not None
        assert loc1.paragraph_index == loc2.paragraph_index
        assert loc1.char_start != loc2.char_start

    def test_figure_table_detected(self) -> None:
        """PM-05: Claim in 'Table 1 shows...' context sets flag."""
        ms = _make_manuscript([
            ("Results", "Table 1 shows Drug X reduces mortality by 30% [7]."),
        ])
        claim = _make_claim(1, "Table 1 shows Drug X reduces mortality by 30%")
        results = map_claims_to_positions([claim], ms)

        loc = results[0].location
        assert loc is not None
        assert loc.in_figure_or_table is True

    def test_no_match_returns_none(self) -> None:
        """PM-06: Completely unrelated text returns location=None."""
        ms = _make_manuscript([
            ("Introduction", "This study examines cardiac outcomes."),
        ])
        claim = _make_claim(1, "CRISPR gene editing revolutionized diagnostics")
        results = map_claims_to_positions([claim], ms)

        assert results[0].location is None

    def test_plain_text_match_ignoring_formatting(self) -> None:
        """PM-07: Matching works even with minor formatting differences."""
        ms = _make_manuscript([
            ("Results", "Drug X significantly reduced all-cause mortality by thirty percent."),
        ])
        # Very similar but not identical
        claim = _make_claim(
            1, "Drug X significantly reduced all-cause mortality by thirty percent",
        )
        results = map_claims_to_positions([claim], ms)

        loc = results[0].location
        assert loc is not None
        assert loc.paragraph_index == 0

    def test_empty_manuscript_text_skipped(self) -> None:
        """Claim with empty manuscript_text gets location=None."""
        ms = _make_manuscript([("Intro", "Some text here.")])
        claim = _make_claim(1, "")
        results = map_claims_to_positions([claim], ms)
        assert results[0].location is None

    def test_multiple_paragraphs_in_section(self) -> None:
        """Sections with multiple paragraphs split correctly."""
        text = "First paragraph about methods.\n\nSecond paragraph about results."
        ms = _make_manuscript([("Methods", text)])
        claim = _make_claim(1, "Second paragraph about results")
        results = map_claims_to_positions([claim], ms)

        loc = results[0].location
        assert loc is not None
        # Second paragraph in the section should have index 1
        assert loc.paragraph_index == 1
