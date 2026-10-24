"""Tests for the section_finder compatibility wrapper (V5 retrieval underneath)."""

from pathlib import Path

import fitz

from refcheck.models.claim import Claim
from refcheck.stages.verify_claims.section_finder import (
    find_relevant_sections,
    find_relevant_sections_with_headings,
    sanitize_text,
)


def _make_claim(text: str) -> Claim:
    return Claim(id=1, extracted_claim=text, reference_ids=[1])


def _create_long_pdf(path: Path, content_sections: list[str]) -> Path:
    """One section of text per page."""
    doc = fitz.open()
    for section_text in content_sections:
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(72, 72, 540, 760), section_text, fontsize=10)
    doc.save(str(path))
    doc.close()
    return path


def _padding(n: int) -> list[str]:
    # Distinct letters per page: blocks repeated on many pages are stripped as headers.
    return [
        f"Padding section {chr(65 + i % 26)}{chr(65 + i // 26)} contains generic text about "
        f"laboratory methodology. It describes routine equipment in detail."
        for i in range(n)
    ]


class TestFindRelevantSections:
    def test_claim_about_mortality_finds_section(self, tmp_path: Path) -> None:
        sections = [
            "Abstract: This paper studies cancer treatments and survival rates.",
            "Drug X was associated with a significant reduction in mortality rates among "
            "elderly patients in the study population.",
        ] + _padding(30)
        pdf_path = _create_long_pdf(tmp_path / "test.pdf", sections)
        result = find_relevant_sections(_make_claim("Drug X reduced mortality in elderly"),
                                        pdf_path)
        assert result
        assert "mortality" in result[0].lower()

    def test_numeric_claim_finds_matching_section(self, tmp_path: Path) -> None:
        sections = [
            "Background: Osteoarthritis is a chronic disease.",
            "Results showed a 30% reduction in inflammation markers after treatment with Drug X.",
        ] + _padding(30)
        pdf_path = _create_long_pdf(tmp_path / "test.pdf", sections)
        result = find_relevant_sections(_make_claim("Drug X reduced inflammation by 30%"),
                                        pdf_path)
        assert "30%" in " ".join(result)

    def test_returns_labelled_passages_within_budget(self, tmp_path: Path) -> None:
        pdf_path = _create_long_pdf(tmp_path / "test.pdf", _padding(120))
        pairs = find_relevant_sections_with_headings(
            _make_claim("laboratory methodology equipment"), pdf_path, max_tokens=500,
        )
        assert pairs
        assert sum(len(text) for _, text in pairs) / 4 <= 500
        assert all(label.startswith("Other") for label, _ in pairs)
        assert any("p." in label for label, _ in pairs)

    def test_empty_pdf_returns_empty(self, tmp_path: Path) -> None:
        pdf_path = tmp_path / "empty.pdf"
        pdf_path.write_bytes(b"not a real pdf")
        assert find_relevant_sections(_make_claim("anything"), pdf_path) == []

    def test_short_pdf_returns_its_text(self, tmp_path: Path) -> None:
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Short abstract about drug efficacy.", fontsize=10)
        doc.save(str(tmp_path / "short.pdf"))
        doc.close()
        result = find_relevant_sections(_make_claim("drug efficacy"), tmp_path / "short.pdf")
        assert len(result) == 1
        assert "drug efficacy" in result[0].lower()

    def test_missing_pdf_returns_empty(self, tmp_path: Path) -> None:
        result = find_relevant_sections(_make_claim("anything"), tmp_path / "nonexistent.pdf")
        assert result == []


def test_sanitize_text_cleans_and_truncates() -> None:
    assert sanitize_text("a\x00b\x07c  d\n\n\n\ne ") == "abc d\n\ne"
    assert sanitize_text("w " * 2100).endswith("[truncated]")
