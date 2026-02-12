"""Tests for section finder (RAG for verification)."""

from pathlib import Path

import fitz
import pytest

from refcheck.models.claim import Claim
from refcheck.stages.verify_claims.section_finder import (
    find_relevant_sections,
    _extract_keywords,
    _extract_numbers,
    _score_section,
)


def _make_claim(text: str) -> Claim:
    """Create a test claim with given text."""
    return Claim(id=1, extracted_claim=text, reference_ids=[1])


def _create_pdf_with_sections(path: Path, sections: list[str]) -> Path:
    """Create a PDF with multiple text sections."""
    doc = fitz.open()
    page = doc.new_page()
    y_offset = 72
    for section in sections:
        page.insert_text((72, y_offset), section, fontsize=10)
        y_offset += 80
    doc.save(str(path))
    doc.close()
    return path


def _create_long_pdf(path: Path, content_sections: list[str]) -> Path:
    """Create a multi-page PDF with separated content sections."""
    doc = fitz.open()
    for section_text in content_sections:
        page = doc.new_page()
        # Write section with enough text to be meaningful
        page.insert_text((72, 72), section_text, fontsize=10)
    doc.save(str(path))
    doc.close()
    return path


class TestKeywordExtraction:
    def test_extracts_keywords(self) -> None:
        kw = _extract_keywords("Drug X reduced mortality by 30%")
        assert "drug" in kw
        assert "reduced" in kw
        assert "mortality" in kw

    def test_removes_stop_words(self) -> None:
        kw = _extract_keywords("the effect of drug on the patient")
        assert "the" not in kw
        assert "drug" in kw
        assert "effect" in kw

    def test_extracts_numbers(self) -> None:
        nums = _extract_numbers("reduced by 30% in 500 patients")
        assert "30%" in nums
        assert "500" in nums


class TestScoreSection:
    def test_matching_keywords_score_positive(self) -> None:
        score = _score_section(
            "Drug X was found to reduce mortality in elderly patients",
            {"drug", "reduce", "mortality"},
            set(),
        )
        assert score > 0

    def test_matching_numbers_boost(self) -> None:
        score_without = _score_section(
            "Drug X reduced mortality in patients",
            {"drug", "mortality"},
            set(),
        )
        score_with = _score_section(
            "Drug X reduced mortality by 30% in patients",
            {"drug", "mortality"},
            {"30%"},
        )
        assert score_with > score_without

    def test_no_keywords_zero_score(self) -> None:
        score = _score_section("anything", set(), set())
        assert score == 0.0


class TestFindRelevantSections:
    def test_claim_about_mortality_finds_section(self, tmp_path: Path) -> None:
        """Claim about mortality reduction finds section containing those words."""
        sections = [
            "Abstract: This paper studies cancer treatments and survival rates.",
            "Drug X was associated with a significant reduction in mortality rates among elderly patients in the study population.",
            "The study used standard statistical methods including regression analysis.",
        ]
        # Create a longer PDF so it doesn't hit the "short PDF" path
        long_sections = sections + [f"Filler paragraph number {i} with enough text to make the PDF long enough for sectioning." for i in range(30)]
        pdf_path = _create_long_pdf(tmp_path / "test.pdf", long_sections)
        claim = _make_claim("Drug X reduced mortality in elderly patients")

        result = find_relevant_sections(claim, pdf_path)
        assert len(result) > 0
        # At least one section should mention mortality
        combined = " ".join(result)
        assert "mortality" in combined.lower()

    def test_numeric_claim_finds_matching_section(self, tmp_path: Path) -> None:
        """Numeric claim '30%' finds section containing '30%'."""
        sections = [
            "Background: Osteoarthritis is a chronic disease.",
            "Results showed a 30% reduction in inflammation markers after treatment with Drug X.",
            "Additional analysis revealed no significant changes in bone density.",
        ]
        long_sections = sections + [f"Padding section {i} contains generic text about methodology." for i in range(30)]
        pdf_path = _create_long_pdf(tmp_path / "test.pdf", long_sections)
        claim = _make_claim("Drug X reduced inflammation by 30%")

        result = find_relevant_sections(claim, pdf_path)
        combined = " ".join(result)
        assert "30%" in combined

    def test_no_match_returns_abstract_fallback(self, tmp_path: Path) -> None:
        """No matching sections returns abstract (first ~500 chars) as fallback."""
        sections = [
            "Abstract of the paper about entirely different topics like astronomy and cosmology.",
        ]
        long_sections = sections + [f"Section {i} about galaxies and star formation in the universe." for i in range(30)]
        pdf_path = _create_long_pdf(tmp_path / "test.pdf", long_sections)
        claim = _make_claim("Nanoparticle drug delivery to joints")

        result = find_relevant_sections(claim, pdf_path)
        # Should fall back to abstract since no sections match
        assert len(result) >= 1

    def test_empty_pdf_returns_empty(self, tmp_path: Path) -> None:
        """Empty/unreadable PDF returns empty list."""
        pdf_path = tmp_path / "empty.pdf"
        pdf_path.write_bytes(b"not a real pdf")
        claim = _make_claim("anything")

        result = find_relevant_sections(claim, pdf_path)
        assert result == []

    def test_short_pdf_returns_full_text(self, tmp_path: Path) -> None:
        """Short PDF (abstract only) returns full text."""
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Short abstract about drug efficacy.", fontsize=10)
        doc.save(str(tmp_path / "short.pdf"))
        doc.close()

        claim = _make_claim("drug efficacy")
        result = find_relevant_sections(claim, tmp_path / "short.pdf")
        assert len(result) == 1
        assert "drug efficacy" in result[0].lower()

    def test_missing_pdf_returns_empty(self, tmp_path: Path) -> None:
        """Non-existent PDF returns empty list."""
        claim = _make_claim("anything")
        result = find_relevant_sections(claim, tmp_path / "nonexistent.pdf")
        assert result == []
