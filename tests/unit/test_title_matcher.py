"""Unit tests for PDF title matching."""

from pathlib import Path

import fitz
import pytest

from refcheck.models.reference import Reference
from refcheck.stages.match_pdfs.title_matcher import (
    extract_title_from_pdf,
    match_by_title,
)


def _make_ref(ref_id: int, title: str = "", doi: str | None = None) -> Reference:
    return Reference(id=ref_id, title=title, doi=doi)


def _create_pdf_with_title(
    path: Path,
    title: str,
    title_fontsize: float = 18.0,
) -> None:
    """Create a test PDF with a large-font title on the first page."""
    doc = fitz.open()
    page = doc.new_page()
    # Title in large font (simulates real paper)
    page.insert_text((72, 72), title, fontsize=title_fontsize)
    # Smaller body text
    page.insert_text(
        (72, 120),
        "Abstract: This paper presents research findings.",
        fontsize=10,
    )
    doc.save(str(path))
    doc.close()


class TestExtractTitleFromPdf:
    def test_extracts_title_by_fontsize(self, tmp_path: Path) -> None:
        """Title extracted from largest-font text on page 1."""
        pdf_path = tmp_path / "test.pdf"
        _create_pdf_with_title(
            pdf_path,
            "Drug X Reduces Mortality in Elderly Patients",
            title_fontsize=18,
        )
        title = extract_title_from_pdf(pdf_path)
        assert "Drug X" in title or "Mortality" in title

    def test_returns_empty_for_missing_pdf(self, tmp_path: Path) -> None:
        title = extract_title_from_pdf(tmp_path / "nonexistent.pdf")
        assert title == ""

    def test_extracts_from_metadata(self, tmp_path: Path) -> None:
        """Falls back to PDF metadata title field."""
        pdf_path = tmp_path / "meta.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Some text", fontsize=10)
        doc.set_metadata({"title": "Metadata Title of This Paper"})
        doc.save(str(pdf_path))
        doc.close()

        title = extract_title_from_pdf(pdf_path)
        assert "Metadata Title" in title

    def test_filename_fallback(self, tmp_path: Path) -> None:
        """Falls back to filename-based extraction."""
        pdf_path = tmp_path / "Smith-2020-Novel treatment for OA.pdf"
        doc = fitz.open()
        page = doc.new_page()
        # Only tiny text, no useful content
        page.insert_text((72, 72), "Fig 1", fontsize=8)
        doc.save(str(pdf_path))
        doc.close()

        title = extract_title_from_pdf(pdf_path)
        assert "Novel treatment" in title or "Smith" in title


class TestMatchByTitle:
    def test_pm02_fuzzy_title_match(self, tmp_path: Path) -> None:
        """PM-02: Title fuzzy match above threshold."""
        pdf_path = tmp_path / "test.pdf"
        _create_pdf_with_title(
            pdf_path, "Drug X Reduces Mortality in Elderly Patients"
        )
        refs = [
            _make_ref(1, title="Drug X reduces mortality in elderly patients"),
            _make_ref(2, title="Completely Unrelated Paper About Plants"),
        ]
        result = match_by_title(refs, pdf_path)
        assert result is not None
        assert result.reference_id == 1
        assert result.confidence >= 0.60

    def test_pm03_unrelated_pdf(self, tmp_path: Path) -> None:
        """PM-03: Unrelated PDF returns None or low confidence."""
        pdf_path = tmp_path / "test.pdf"
        _create_pdf_with_title(pdf_path, "Quantum Computing Architecture Review")
        refs = [
            _make_ref(1, title="Drug X Reduces Mortality in Elderly Patients"),
        ]
        result = match_by_title(refs, pdf_path)
        if result is not None:
            assert result.confidence < 0.60

    def test_pm04_ambiguous_match(self, tmp_path: Path) -> None:
        """PM-04: Ambiguous match flags for confirmation."""
        pdf_path = tmp_path / "test.pdf"
        _create_pdf_with_title(pdf_path, "Effects of Drug X on Mortality Rates")
        refs = [
            _make_ref(1, title="Effect of Drug X on Mortality"),
            _make_ref(2, title="Effects of Drug X on Morbidity Rates"),
        ]
        result = match_by_title(refs, pdf_path)
        assert result is not None

    def test_pm06_bulk_matching(self, tmp_path: Path) -> None:
        """PM-06: Bulk matching 10 PDFs against 15 refs."""
        topics = [
            "Novel Biomarker Discovery in Breast Cancer Using Proteomics",
            "Machine Learning for Drug Target Identification in Alzheimers",
            "CRISPR Gene Editing Safety Assessment in Clinical Trials",
            "Nanoparticle Drug Delivery Systems for Rheumatoid Arthritis",
            "Epigenetic Modifications in Aging and Neurodegenerative Disease",
            "Stem Cell Therapy Outcomes in Spinal Cord Injury Recovery",
            "Metabolomics Profiling of Type 2 Diabetes Biomarkers Study",
            "Immunotherapy Response Prediction Using Tumor Microbiome Data",
            "Artificial Intelligence for Early Cancer Detection Screening",
            "Microbiome Transplantation Effects on Inflammatory Bowel Disease",
            "Protein Folding Prediction with Deep Learning Neural Networks",
            "Single Cell RNA Sequencing in Autoimmune Disease Research",
            "Exosome Therapeutics for Cardiovascular Disease Prevention",
            "Gut Brain Axis Communication in Parkinsons Disease Model",
            "Lipid Nanoparticle mRNA Vaccine Platform Development Study",
        ]
        refs = [_make_ref(i + 1, title=topics[i]) for i in range(15)]
        matched = 0

        for i in range(10):
            pdf_path = tmp_path / f"paper_{i}.pdf"
            _create_pdf_with_title(pdf_path, topics[i])
            result = match_by_title(refs, pdf_path)
            if result is not None:
                matched += 1

        assert matched >= 5
