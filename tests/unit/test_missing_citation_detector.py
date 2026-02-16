"""Tests for missing citation detection."""

from refcheck.models.citation import CitationInstance, MissingCitation
from refcheck.models.reference import ManuscriptSection, ParsedManuscript
from refcheck.stages.detect_citations.missing_citation_detector import (
    detect_missing_citations,
)


def _make_manuscript(sections: list[tuple[str, str]]) -> ParsedManuscript:
    return ParsedManuscript(
        filename="test.docx",
        sections=[
            ManuscriptSection(heading=h, text=t) for h, t in sections
        ],
    )


class TestMissingCitationDetector:
    def test_flags_statistical_claim(self) -> None:
        ms = _make_manuscript([
            ("Results", "The mortality rate was 30% in untreated patients."),
        ])
        result = detect_missing_citations(ms, [])
        assert len(result) >= 1
        found = any("30%" in mc.sentence_text for mc in result)
        assert found

    def test_skips_author_own_work(self) -> None:
        ms = _make_manuscript([
            ("Results", "We found that hydrogels improved survival."),
        ])
        result = detect_missing_citations(ms, [])
        assert len(result) == 0

    def test_skips_structural_text(self) -> None:
        ms = _make_manuscript([
            ("Methods", "In this section, we review the methodology used in detail."),
        ])
        result = detect_missing_citations(ms, [])
        assert len(result) == 0

    def test_flags_attribution_without_citation(self) -> None:
        ms = _make_manuscript([
            ("Introduction", "Previous studies have shown that X increases Y significantly."),
        ])
        result = detect_missing_citations(ms, [])
        assert len(result) >= 1

    def test_flags_historical_claim(self) -> None:
        ms = _make_manuscript([
            ("Introduction", "The technique was first described in 1990 by researchers at MIT."),
        ])
        result = detect_missing_citations(ms, [])
        assert len(result) >= 1

    def test_skips_short_sentences(self) -> None:
        ms = _make_manuscript([
            ("Results", "See above."),
        ])
        result = detect_missing_citations(ms, [])
        assert len(result) == 0

    def test_skips_reference_section(self) -> None:
        ms = _make_manuscript([
            ("References", "Smith et al. 2020. A study of X."),
        ])
        result = detect_missing_citations(ms, [])
        assert len(result) == 0
