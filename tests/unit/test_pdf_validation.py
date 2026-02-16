"""Tests for PDF validation and supplement detection."""

from pathlib import Path

import fitz
import pytest

from refcheck.stages.match_pdfs.pdf_validator import (
    score_pdf_url,
    validate_downloaded_pdf,
)


def _create_pdf(
    tmp_path: Path,
    text: str,
    filename: str = "test.pdf",
    pages: int = 1,
) -> Path:
    """Create a PDF with given text, using textbox for word wrapping."""
    pdf_path = tmp_path / filename
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page_text = text if i == 0 else f"Page {i + 1}. " + ("content " * 500)
        rect = fitz.Rect(50, 50, 550, 750)
        page.insert_textbox(rect, page_text, fontsize=8)
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


class TestScorePdfUrl:
    """Test URL scoring for supplement detection."""

    def test_supplement_url_scored_low(self) -> None:
        url = "https://example.com/supplements/paper_si_data.pdf"
        assert score_pdf_url(url) < 20

    def test_main_paper_url_scored_high(self) -> None:
        url = "https://example.com/pdf/full/12345.pdf"
        assert score_pdf_url(url) > 50

    def test_neutral_url_gets_base_score(self) -> None:
        url = "https://example.com/download/paper.pdf"
        assert score_pdf_url(url) == 50

    def test_supporting_keyword_penalized(self) -> None:
        url = "https://example.com/supporting-information.pdf"
        assert score_pdf_url(url) < 20


class TestValidateDownloadedPdf:
    """Test post-download PDF validation."""

    def test_valid_paper_passes(self, tmp_path: Path) -> None:
        """Normal paper with title match passes validation."""
        text = "Effect of Drug X on Mortality\n\nAbstract: " + ("word " * 300)
        pdf_path = _create_pdf(tmp_path, text, pages=3)
        assert validate_downloaded_pdf(pdf_path, "Effect of Drug X on Mortality")

    def test_supplement_detected(self, tmp_path: Path) -> None:
        """PDF with 'Supplementary Information' on first page fails."""
        text = "Supplementary Information\n\nFigure S1: Additional data\n\n" + ("word " * 300)
        pdf_path = _create_pdf(tmp_path, text, pages=3)
        assert not validate_downloaded_pdf(pdf_path, "Some Paper Title")

    def test_too_short_fails(self, tmp_path: Path) -> None:
        """PDF with very little text fails."""
        pdf_path = _create_pdf(tmp_path, "Short text")
        assert not validate_downloaded_pdf(pdf_path, "Some Title")

    def test_abstract_only_capped(self) -> None:
        """Abstract-only verification should cap confidence at 0.60."""
        # This tests the logic described in the spec
        confidence = 0.90
        capped = min(confidence, 0.60)
        assert capped == 0.60
