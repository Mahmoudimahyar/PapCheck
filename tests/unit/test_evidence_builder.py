"""Tests for evidence section builder."""

from refcheck.stages.verify_claims.evidence_builder import (
    build_evidence_sections,
    classify_match,
    extract_numbers,
)


class TestBuildEvidenceSections:
    def test_direct_quote_found(self) -> None:
        """ES-01: Direct quote in source found at correct position."""
        source = ["Drug X resulted in a 28% reduction in mortality (p=0.003)."]
        headings = ["Results"]
        quotes = ["28% reduction in mortality"]
        sections = build_evidence_sections(
            source, headings, quotes, source[0], "Drug X reduced mortality by 30%",
        )
        assert len(sections) == 1
        assert sections[0].section_heading == "Results"
        assert len(sections[0].quote_highlights) == 1
        qh = sections[0].quote_highlights[0]
        assert qh.char_start == 21
        assert qh.char_end == 47
        assert qh.match_type == "numeric_mismatch"

    def test_paraphrased_content(self) -> None:
        """ES-02: Paraphrased content classified correctly."""
        source_text = (
            "The experimental treatment significantly reduced "
            "cardiac event incidence among elderly subjects."
        )
        # LLM extracted a paraphrased version — close but not identical
        quote = "experimental treatment significantly reduced cardiac events"
        sections = build_evidence_sections(
            [source_text], ["Results"], [quote], source_text,
            "Drug X reduced cardiac events in elderly",
        )
        assert len(sections) == 1
        highlights = sections[0].quote_highlights
        assert len(highlights) == 1
        assert highlights[0].match_type in ("paraphrased", "direct")

    def test_numeric_mismatch(self) -> None:
        """ES-03: '30%' in claim but '28%' in source → numeric_mismatch."""
        source_text = "The treatment resulted in a 28% reduction."
        quote = "28% reduction"
        sections = build_evidence_sections(
            [source_text], ["Results"], [quote], source_text,
            "Drug X reduced mortality by 30%",
        )
        highlights = sections[0].quote_highlights
        assert len(highlights) == 1
        assert highlights[0].match_type == "numeric_mismatch"

    def test_absent_quote(self) -> None:
        """ES-04: Quote not in any section → not added."""
        source_text = "Unrelated content about gene therapy protocols."
        quote = "completely different topic about climate change"
        sections = build_evidence_sections(
            [source_text], ["Methods"], [quote], source_text,
            "Climate change affects health",
        )
        # Should have 0 highlights since quote doesn't match at all
        assert len(sections[0].quote_highlights) == 0

    def test_multiple_quotes_across_sections(self) -> None:
        """ES-05: Quotes placed in correct sections."""
        s1 = "Methods: We used a randomized controlled trial design."
        s2 = "Results: Drug X resulted in a 28% reduction in mortality."
        quotes = ["randomized controlled trial", "28% reduction in mortality"]
        sections = build_evidence_sections(
            [s1, s2], ["Methods", "Results"], quotes,
            s1 + "\n\n" + s2, "Drug X reduced mortality by 30%",
        )
        assert len(sections) == 2
        # First quote should be in first section
        assert len(sections[0].quote_highlights) == 1
        assert sections[0].quote_highlights[0].quote == "randomized controlled trial"
        # Second quote should be in second section
        assert len(sections[1].quote_highlights) == 1

    def test_number_extraction(self) -> None:
        """ES-06: Number extraction works for percentages, decimals, ints."""
        nums = extract_numbers("30% reduction, p=0.003, n=500, 12.5% CI")
        assert "30%" in nums
        assert "0.003" in nums
        assert "500" in nums
        assert "12.5%" in nums

    def test_empty_evidence_quotes(self) -> None:
        """ES-07: Empty evidence quotes → sections still stored."""
        sections = build_evidence_sections(
            ["Some source text."], ["Results"], [], "Some source text.",
            "A claim about results",
        )
        assert len(sections) == 1
        assert sections[0].full_text == "Some source text."
        assert sections[0].quote_highlights == []

    def test_quote_in_best_matching_section(self) -> None:
        """ES-08: Quote found in section with best match."""
        s1 = "Background: General overview of the disease."
        s2 = "Results: Drug X resulted in a 28% reduction in mortality."
        sections = build_evidence_sections(
            [s1, s2], ["Background", "Results"],
            ["28% reduction in mortality"],
            s1 + "\n\n" + s2, "Drug X reduced mortality",
        )
        # Quote should be in section 2, not section 1
        assert len(sections[1].quote_highlights) == 1
        assert len(sections[0].quote_highlights) == 0


class TestClassifyMatch:
    def test_direct_high_similarity(self) -> None:
        result = classify_match("exact text", "exact text", "exact text claim", 0.99)
        assert result == "direct"

    def test_paraphrased_medium_similarity(self) -> None:
        result = classify_match("slightly off", "slightly different", "no numbers", 0.80)
        assert result == "paraphrased"

    def test_numeric_mismatch_detected(self) -> None:
        result = classify_match(
            "28% reduction", "28% reduction",
            "30% reduction in mortality", 0.90,
        )
        assert result == "numeric_mismatch"

    def test_absent_low_similarity(self) -> None:
        result = classify_match("q", "different", "claim", 0.50)
        assert result == "absent"
