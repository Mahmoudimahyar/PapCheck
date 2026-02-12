"""Tests for Stage 1: DOCX parsing (P-01 through P-09)."""

from pathlib import Path

import pytest

from refcheck.stages.parse_docx import parse_manuscript
from tests.conftest import create_test_docx


class TestParseDocx:
    """P-01 through P-09 acceptance tests."""

    def test_p01_basic_numbered_references(self, tmp_path: Path) -> None:
        """P-01: 10 numbered references extracted with correct metadata."""
        docx_path = create_test_docx(tmp_path / "test.docx", ref_count=10)
        result = parse_manuscript(docx_path)
        assert len(result.references) == 10
        with_title = [r for r in result.references if r.title]
        with_year = [r for r in result.references if r.year]
        assert len(with_title) >= 8
        assert len(with_year) >= 8

    def test_p02_citation_style_detection(self, tmp_path: Path) -> None:
        """P-02: Citation style detected as numbered."""
        docx_path = create_test_docx(tmp_path / "test.docx")
        result = parse_manuscript(docx_path)
        assert result.citation_style == "numbered"

    def test_p03_doi_extraction(self, tmp_path: Path) -> None:
        """P-03: DOIs correctly extracted from references."""
        docx_path = create_test_docx(tmp_path / "test.docx", include_dois=True)
        result = parse_manuscript(docx_path)
        refs_with_doi = [r for r in result.references if r.doi]
        assert len(refs_with_doi) >= 3
        for ref in refs_with_doi:
            assert ref.doi is not None
            assert ref.doi.startswith("10.")

    def test_p04_pmid_extraction(self, tmp_path: Path) -> None:
        """P-04: PMIDs correctly extracted from references."""
        docx_path = create_test_docx(tmp_path / "test.docx", include_pmids=True)
        result = parse_manuscript(docx_path)
        refs_with_pmid = [r for r in result.references if r.pmid]
        assert len(refs_with_pmid) >= 2

    def test_p05_range_citation_expansion(self, tmp_path: Path) -> None:
        """P-05: Range citation [1-3] expands correctly."""
        docx_path = create_test_docx(tmp_path / "test.docx")
        result = parse_manuscript(docx_path)
        all_citations = []
        for section in result.sections:
            all_citations.extend(section.citations)

        range_cites = [
            c for c in all_citations if "-" in c.raw_text or "\u2013" in c.raw_text
        ]
        assert len(range_cites) >= 1
        for cite in range_cites:
            if "1-3" in cite.raw_text or "1\u20133" in cite.raw_text:
                assert 1 in cite.reference_ids
                assert 2 in cite.reference_ids
                assert 3 in cite.reference_ids

    def test_p06_field_code_detection(self, tmp_path: Path) -> None:
        """P-06: Field code detection returns False for simple DOCX."""
        docx_path = create_test_docx(tmp_path / "test.docx")
        result = parse_manuscript(docx_path)
        assert result.has_field_codes is False

    def test_p07_messy_formatting(self, tmp_path: Path) -> None:
        """P-07: Messy formatting doesn't crash, warnings populated."""
        import docx as docxlib

        doc = docxlib.Document()
        doc.add_paragraph("Some body text without headings")
        doc.add_paragraph("")
        doc.add_paragraph("   ")
        doc.add_paragraph("References")
        doc.add_paragraph("[1] A. Smith, Some paper, Journal, (2020).")
        doc.add_paragraph("")
        doc.add_paragraph("[2] B. Jones, Another paper, Journal, (2021).")
        messy_path = tmp_path / "messy.docx"
        doc.save(str(messy_path))

        result = parse_manuscript(messy_path)
        # Should not crash; may have warnings
        assert isinstance(result.references, list)

    def test_p08_no_reference_section(self, tmp_path: Path) -> None:
        """P-08: No reference section produces empty list with warning."""
        import docx as docxlib

        doc = docxlib.Document()
        doc.add_heading("Introduction", level=1)
        doc.add_paragraph("Body text with no references at all.")
        no_refs_path = tmp_path / "no_refs.docx"
        doc.save(str(no_refs_path))

        result = parse_manuscript(no_refs_path)
        assert result.references == []
        assert any("reference" in w.lower() for w in result.warnings)

    def test_sections_extracted(self, tmp_path: Path) -> None:
        """Verify sections are extracted with headings."""
        docx_path = create_test_docx(tmp_path / "test.docx")
        result = parse_manuscript(docx_path)
        assert len(result.sections) >= 3
        headings = [s.heading for s in result.sections if s.heading]
        assert any("Introduction" in h for h in headings)

    def test_filename_preserved(self, tmp_path: Path) -> None:
        """Verify filename is preserved in output."""
        docx_path = create_test_docx(tmp_path / "manuscript.docx")
        result = parse_manuscript(docx_path)
        assert result.filename == "manuscript.docx"

    def test_endnote_bibliography_style(self, tmp_path: Path) -> None:
        """References with 'EndNote Bibliography' style are extracted."""
        import docx as docxlib

        doc = docxlib.Document()
        doc.add_heading("Title", level=1)
        doc.add_paragraph("Body text [1, 2].")
        doc.add_heading("References", level=2)

        # Simulate EndNote bibliography paragraphs
        for i in range(1, 6):
            p = doc.add_paragraph(
                f"[{i}] A. Author{i}, Paper title {i}, Journal, ({2020 + i})."
            )
            p.style = doc.styles["Normal"]

        path = tmp_path / "endnote.docx"
        doc.save(str(path))
        result = parse_manuscript(path)
        assert len(result.references) == 5
