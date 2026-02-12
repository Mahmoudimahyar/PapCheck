"""Unit tests for PDF DOI matching."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from refcheck.models.reference import Reference
from refcheck.stages.match_pdfs.doi_matcher import extract_doi_from_pdf, match_by_doi


def _make_ref(ref_id: int, doi: str | None = None, title: str = "") -> Reference:
    return Reference(id=ref_id, title=title, doi=doi)


class TestExtractDoiFromPdf:
    def test_extracts_doi_from_metadata(self, tmp_path: Path) -> None:
        """Test DOI extraction from PDF metadata."""
        pdf_path = tmp_path / "test.pdf"
        _create_test_pdf(pdf_path, doi="10.1016/test.2020")
        doi = extract_doi_from_pdf(pdf_path)
        assert doi is not None
        assert doi.startswith("10.")

    def test_returns_none_for_missing_pdf(self, tmp_path: Path) -> None:
        doi = extract_doi_from_pdf(tmp_path / "nonexistent.pdf")
        assert doi is None


class TestMatchByDoi:
    def test_pm01_exact_doi_match(self, tmp_path: Path) -> None:
        """PM-01: DOI exact match returns high confidence."""
        pdf_path = tmp_path / "test.pdf"
        _create_test_pdf(pdf_path, doi="10.1016/test.2020")

        refs = [
            _make_ref(1, doi="10.1016/test.2020", title="Test Paper"),
            _make_ref(2, doi="10.1038/other", title="Other Paper"),
        ]
        result = match_by_doi(refs, pdf_path)
        assert result is not None
        assert result.reference_id == 1
        assert result.confidence >= 0.95
        assert result.match_method == "doi"

    def test_no_doi_in_pdf(self, tmp_path: Path) -> None:
        """No DOI in PDF returns None."""
        pdf_path = tmp_path / "test.pdf"
        _create_test_pdf(pdf_path)  # No DOI
        refs = [_make_ref(1, doi="10.1016/test")]
        result = match_by_doi(refs, pdf_path)
        assert result is None

    def test_doi_not_in_references(self, tmp_path: Path) -> None:
        """PDF DOI doesn't match any reference."""
        pdf_path = tmp_path / "test.pdf"
        _create_test_pdf(pdf_path, doi="10.9999/unrelated")
        refs = [_make_ref(1, doi="10.1016/test")]
        result = match_by_doi(refs, pdf_path)
        assert result is None


def _create_test_pdf(path: Path, doi: str = "", title: str = "Test Paper") -> None:
    """Create a minimal test PDF with optional DOI in first-page text."""
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    text = f"{title}\n"
    if doi:
        text += f"\nhttps://doi.org/{doi}\n"
    page.insert_text((72, 72), text, fontsize=12)
    doc.save(str(path))
    doc.close()
