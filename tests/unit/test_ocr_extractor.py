"""Tests for OCR extractor and PDF text extraction."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import fitz
import pytest

from refcheck.stages.match_pdfs.ocr_extractor import (
    extract_text_with_ocr_fallback,
)


def _create_text_pdf(tmp_path: Path, content: str) -> Path:
    """Create a PDF with text content."""
    pdf_path = tmp_path / "text.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), content, fontsize=10)
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def _create_empty_pdf(tmp_path: Path) -> Path:
    """Create a PDF with no text (simulates scanned)."""
    pdf_path = tmp_path / "empty.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


class TestOCRExtractor:
    """Test OCR fallback for text extraction."""

    def test_text_pdf_extracts_normally(self, tmp_path: Path) -> None:
        """Text-based PDF extracts without needing OCR."""
        content = "This is a test document with sufficient text content for extraction."
        pdf_path = _create_text_pdf(tmp_path, content)
        result = extract_text_with_ocr_fallback(pdf_path)
        assert "test document" in result

    def test_empty_page_triggers_ocr_attempt(self, tmp_path: Path) -> None:
        """Pages with <50 chars text trigger OCR attempt."""
        pdf_path = _create_empty_pdf(tmp_path)

        # Mock _try_ocr_page to verify it's called
        with patch(
            "refcheck.stages.match_pdfs.ocr_extractor._try_ocr_page",
            return_value="OCR extracted text content here",
        ) as mock_ocr:
            result = extract_text_with_ocr_fallback(pdf_path)
            mock_ocr.assert_called_once()
            assert "OCR extracted text" in result

    def test_graceful_without_pytesseract(self, tmp_path: Path) -> None:
        """Graceful degradation when pytesseract not installed."""
        pdf_path = _create_empty_pdf(tmp_path)

        # Simulate ImportError when trying OCR
        with patch(
            "refcheck.stages.match_pdfs.ocr_extractor._try_ocr_page",
            return_value=None,
        ):
            result = extract_text_with_ocr_fallback(pdf_path)
            # Should return empty string, not crash
            assert isinstance(result, str)
