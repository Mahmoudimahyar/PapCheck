"""M8: repository cover sheets and image-only (scanned) PDFs are never verified against."""

import asyncio
from pathlib import Path

import fitz
import pytest

from refcheck.models.reference import Reference
from refcheck.stages.verify_claims import source_ocr, source_pdf
from refcheck.stages.verify_claims.source_document import load_pdf_document, load_source_document
from refcheck.stages.verify_claims.source_pdf import clear_pdf_cache, extract_pdf_pages
from refcheck.stages.verify_claims.source_scan import (
    PageStats,
    is_cover_sheet,
    scan_report,
)
from refcheck.stages.verify_claims.verifier_helpers import resolve_source

# Synthetic cover sheet in the style of a university research-portal download.
_COVER = (
    "University of Groningen\nSynthetic microcapsules protect beta cells in vitro\n"
    "Doe, Jane; Roe, Kim\nPublished in: Journal of Synthetic Tests\n"
    "Document Version\nPublisher's PDF, also known as Version of record\n"
    "Citation for published version (APA): Doe, J. (2022).\nLink to publication\n"
    "Take-down policy\nIf you believe that this document breaches copyright please contact us.\n"
    "Download date: 01-01-2025"
)
_ABSTRACT = ("Alginate microcapsules protect transplanted islets from immune attack without "
             "systemic immunosuppression, and extracellular matrix components improve the "
             "survival of encapsulated beta cells under cytokine stress in vitro. Capsules "
             "with matrix proteins kept insulin secretion stable for two whole weeks.")
_PROSE = ("Encapsulated islets were cultured for seven days. Viability was measured daily. "
          "Cytokine exposure reduced viability in controls but not in treated capsules. ") * 8


@pytest.fixture(autouse=True)
def _no_real_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFCHECK_OCR", "0")  # tesseract may be installed on the test machine
    clear_pdf_cache()


def _image_page(doc: fitz.Document) -> None:
    page = doc.new_page()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 40), False)
    pix.clear_with(180)
    page.insert_image(page.rect, pixmap=pix)


def _text_page(doc: fitz.Document, text: str) -> None:
    doc.new_page().insert_textbox(fitz.Rect(40, 40, 560, 800), text, fontsize=9)


def _scanned_pdf(path: Path, cover: bool = True, n_images: int = 4) -> Path:
    doc = fitz.open()
    if cover:
        _text_page(doc, _COVER)
    for _ in range(n_images):
        _image_page(doc)
    doc.save(str(path))
    doc.close()
    return path


def _ref(pdf: Path, abstract: str | None = _ABSTRACT) -> Reference:
    return Reference(id=87, title="Synthetic microcapsules protect beta cells in vitro",
                     pdf_path=pdf, abstract_text=abstract,
                     abstract_source="pubmed" if abstract else None, source_status="found")


class TestCoverSheet:
    def test_repository_cover_detected(self) -> None:
        assert is_cover_sheet(_COVER)

    def test_accepted_manuscript_cover_detected(self) -> None:
        text = ("This is the author manuscript accepted for publication and has undergone full "
                "peer review. Please cite this article as doi: 10.5555/x.1. This article is "
                "protected by copyright. All rights reserved")
        assert is_cover_sheet(text)

    def test_accepted_manuscript_first_page_with_abstract_is_not_a_cover(self) -> None:
        """Integration review: the full AAM disclaimer (4 cover phrases) above the title
        and abstract made the article's first page count as a cover sheet."""
        text = ("This is the author manuscript accepted for publication and has undergone full "
                "peer review but has not been through the copyediting, which may lead to "
                "differences between this version and the Version of Record. Please cite this "
                "article as doi: 10.5555/x.1\nSynthetic hydrogels in mice\nAbstract\n"
                + _PROSE + "\nThis article is protected by copyright. All rights reserved")
        assert not is_cover_sheet(text)

    def test_long_prose_page_is_not_a_cover(self) -> None:
        assert not is_cover_sheet(_COVER + "\n" + " ".join(["word"] * 520))

    def test_real_first_page_with_one_footer_phrase_is_not_a_cover(self) -> None:
        text = "Synthetic hydrogels\nAbstract\n" + _PROSE + "\nThis article is protected by " \
               "copyright. All rights reserved"
        assert not is_cover_sheet(text)


class TestScanReport:
    def test_mostly_image_pages_is_scanned(self) -> None:
        pages = [PageStats(chars=0, words=0, images=1)] * 16
        assert scan_report(pages).scanned

    def test_article_with_figure_pages_is_not_scanned(self) -> None:
        text = [PageStats(chars=6000, words=900, images=0)] * 4
        figures = [PageStats(chars=40, words=6, images=1)] * 5
        assert not scan_report(text + figures).scanned  # 3,600 words of real text

    def test_blank_pages_ignored(self) -> None:
        pages = [PageStats(chars=5000, words=800, images=0), PageStats()]
        assert not scan_report(pages).scanned


class TestExtraction:
    def test_cover_dropped_and_scan_flagged(self, tmp_path: Path) -> None:
        pdf = extract_pdf_pages(_scanned_pdf(tmp_path / "qin2022.pdf"))
        assert pdf.cover_sheet_removed and pdf.scanned
        assert pdf.image_only_pages == 4 and pdf.n_pages == 5 and pdf.ocr_pages == 0
        assert "Take-down policy" not in pdf.text

    def test_scanned_pdf_document_is_unusable(self, tmp_path: Path) -> None:
        # Before M8 the cover sheet's title/author text became the "full text".
        doc = load_pdf_document(_scanned_pdf(tmp_path / "scan.pdf"), 87)
        assert doc.quality_reason == "pdf_scanned" and doc.quality_score == 0.0
        assert not doc.chunks and doc.cover_sheet_removed

    def test_falls_back_to_abstract(self, tmp_path: Path) -> None:
        ref = _ref(_scanned_pdf(tmp_path / "scan.pdf"))
        doc = load_source_document(ref)
        assert doc is not None and doc.coverage == "abstract_only"
        assert doc.quality_reason == "pdf_scanned"
        src = asyncio.run(resolve_source(ref))
        assert src.coverage == "abstract_only" and "scan" in src.detail

    def test_without_abstract_cannot_verify_pdf_scanned(self, tmp_path: Path) -> None:
        src = asyncio.run(resolve_source(_ref(_scanned_pdf(tmp_path / "s.pdf"), abstract=None)))
        assert src.doc is None and src.cannot_verify_reason == "pdf_scanned"

    def test_ocr_text_used_when_available(self, tmp_path: Path,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(source_pdf, "ocr_available", lambda: True)
        monkeypatch.setattr(source_pdf, "ocr_page_text", lambda page: _PROSE + "\n\n" + _PROSE)
        path = _scanned_pdf(tmp_path / "ocr.pdf")
        pdf = extract_pdf_pages(path)
        assert pdf.scanned and pdf.ocr_pages == 4 and "Encapsulated islets" in pdf.text
        doc = load_pdf_document(path, 87)
        assert doc.ocr_pages == 4 and doc.chunks and doc.quality_reason != "pdf_scanned"
        src = asyncio.run(resolve_source(_ref(path)))
        assert src.coverage == "full_text" and "OCR" in src.detail

    def test_text_pdf_unchanged(self, tmp_path: Path) -> None:
        doc = fitz.open()
        _text_page(doc, "Abstract\n" + _PROSE)
        _text_page(doc, "Results\n" + _PROSE)
        doc.save(str(tmp_path / "text.pdf"))
        doc.close()
        pdf = extract_pdf_pages(tmp_path / "text.pdf")
        assert not pdf.scanned and not pdf.cover_sheet_removed and "Encapsulated" in pdf.text


class TestOcrAvailability:
    def test_disabled_by_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REFCHECK_OCR", "0")
        assert not source_ocr.ocr_available()

    def test_no_binary_means_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REFCHECK_OCR", "1")
        monkeypatch.setattr(source_ocr, "find_tesseract", lambda: None)
        assert not source_ocr.ocr_available()

    def test_configured_binary_found(self, tmp_path: Path,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
        exe = tmp_path / "tesseract.exe"
        exe.write_bytes(b"")
        monkeypatch.setenv("TESSERACT_CMD", str(exe))
        assert source_ocr.find_tesseract() == str(exe)

    def test_windows_install_folder_found(self, tmp_path: Path,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "Tesseract-OCR").mkdir()
        (tmp_path / "Tesseract-OCR" / "tesseract.exe").write_bytes(b"")
        monkeypatch.delenv("TESSERACT_CMD", raising=False)
        monkeypatch.setattr(source_ocr.shutil, "which", lambda name: None)
        monkeypatch.setenv("ProgramFiles", str(tmp_path))
        assert source_ocr.find_tesseract() == str(tmp_path / "Tesseract-OCR" / "tesseract.exe")
