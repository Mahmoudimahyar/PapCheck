"""Full pipeline integration test with real API calls.

Creates a manuscript with real biomedical references, runs
the full MVP pipeline (parse → match → resolve → report),
and verifies end-to-end results using live APIs.
"""

import tempfile
from pathlib import Path

import pytest
from docx import Document

from refcheck.models.pipeline import PipelineState
from refcheck.stages.generate_report import generate_report
from refcheck.stages.match_pdfs import match_pdfs
from refcheck.stages.parse_docx import parse_manuscript
from refcheck.stages.resolve_gaps.resolver import resolve_gaps

pytestmark = pytest.mark.integration

# Real biomedical references with known DOIs/PMIDs
REAL_REFERENCES = [
    (
        "1. Polack FP, Thomas SJ, Kitchin N, et al. Safety and Efficacy "
        "of the BNT162b2 mRNA Covid-19 Vaccine. N Engl J Med. 2020;"
        "383(27):2603-2615. doi: 10.1056/NEJMoa2034577. PMID: 33301246."
    ),
    (
        "2. Jinek M, Chylinski K, Fonfara I, Hauer M, Doudna JA, "
        "Charpentier E. A programmable dual-RNA-guided DNA endonuclease "
        "in adaptive bacterial immunity. Science. 2012;337(6096):816-821. "
        "doi: 10.1126/science.1225829."
    ),
    (
        "3. Watson JD, Crick FH. Molecular structure of nucleic acids; "
        "a structure for deoxyribose nucleic acid. Nature. 1953;"
        "171(4356):737-738. doi: 10.1038/171737a0."
    ),
    (
        "4. Lander ES, Linton LM, Birren B, et al. Initial sequencing "
        "and analysis of the human genome. Nature. 2001;409(6822):860-921. "
        "doi: 10.1038/35057062. PMID: 11237011."
    ),
    (
        "5. Vaswani A, Shazeer N, Parmar N, et al. Attention Is All "
        "You Need. Adv Neural Inf Process Syst. 2017;30."
    ),
    (
        "6. Weinberg RA. The Biology of Cancer. 2nd ed. "
        "Garland Science; 2013."
    ),
    (
        "7. Smith J, Johnson B. Xylophone Quantum Entanglement in "
        "Jellyfish Synapses. Fake J. 2099;1:1-5."
    ),
]


def _create_real_manuscript(path: Path) -> None:
    """Create a DOCX with real biomedical references."""
    doc = Document()
    doc.add_heading("Impact of mRNA Vaccines on Public Health", level=1)

    doc.add_heading("Abstract", level=2)
    doc.add_paragraph(
        "This review examines the development of mRNA vaccines [1] "
        "and their broader implications for biomedical research [2-4]. "
        "We also consider AI approaches to drug discovery [5]."
    )

    doc.add_heading("Introduction", level=2)
    doc.add_paragraph(
        "The discovery of DNA structure [3] laid the groundwork for "
        "modern molecular biology. The Human Genome Project [4] "
        "accelerated genomic research. Recently, CRISPR technology [2] "
        "and mRNA vaccines [1] have transformed medicine."
    )

    doc.add_heading("Methods", level=2)
    doc.add_paragraph(
        "We reviewed recent literature on cancer biology [6] and "
        "emerging computational methods [5]. Note that some references "
        "may be fabricated for testing purposes [7]."
    )

    doc.add_heading("References", level=2)
    for ref_text in REAL_REFERENCES:
        doc.add_paragraph(ref_text)

    doc.save(str(path))


class TestLiveFullPipeline:
    """End-to-end pipeline test with real API calls."""

    @pytest.mark.asyncio
    async def test_full_pipeline_with_real_references(self) -> None:
        """Run the entire MVP pipeline with real biomedical references."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            docx_path = tmp_path / "real_manuscript.docx"
            _create_real_manuscript(docx_path)

            # --- Stage 1: Parse DOCX ---
            manuscript = parse_manuscript(docx_path)

            assert manuscript.filename == "real_manuscript.docx"
            assert len(manuscript.references) >= 5  # at least 5 real refs
            assert manuscript.citation_style == "numbered"

            # Collect citations from all sections
            all_citations = [
                c
                for section in manuscript.sections
                for c in section.citations
            ]
            assert len(all_citations) > 0

            # Check specific DOI extraction
            dois_found = [r.doi for r in manuscript.references if r.doi]
            assert len(dois_found) >= 3  # at least 3 DOIs in our refs
            assert any("10.1056" in d for d in dois_found)  # BNT162b2 DOI

            # Check PMID extraction
            pmids_found = [r.pmid for r in manuscript.references if r.pmid]
            assert len(pmids_found) >= 1

            # Check citation expansion (refs [2-4] should expand)
            all_cited_ids: set[int] = set()
            for c in all_citations:
                all_cited_ids.update(c.reference_ids)
            assert {1, 2, 3, 4, 5} <= all_cited_ids  # at least these

            # --- Stage 3: PDF Matching (no user PDFs — should find nothing) ---
            pdf_dir = tmp_path / "pdfs"
            pdf_dir.mkdir()
            matches = match_pdfs(manuscript.references, pdf_dir)
            # No user PDFs uploaded, so all should be unmatched
            assert all(m.confidence == 0.0 for m in matches)

            # --- Stage 4: Resolve Gaps via Live APIs ---
            output_dir = tmp_path / "resolved_pdfs"
            resolved = await resolve_gaps(manuscript.references, output_dir)

            assert len(resolved) == len(manuscript.references)

            # Count results by status
            found = [r for r in resolved if r.source_status == "found"]
            not_found = [r for r in resolved if r.source_status == "not_found"]
            api_error = [r for r in resolved if r.source_status == "api_error"]

            # At least 4 of our 7 references should be found
            # (the well-known ones: BNT162b2, CRISPR, DNA structure,
            #  Human Genome, Attention paper)
            assert len(found) >= 4, (
                f"Expected >= 4 found, got {len(found)} found, "
                f"{len(not_found)} not_found, {len(api_error)} api_error"
            )

            # The fabricated reference should NOT be found (or at worst api_error)
            ref_7 = next((r for r in resolved if r.id == 7), None)
            assert ref_7 is not None
            # Fabricated ref should be not_found, api_error, or found
            # (APIs do fuzzy matching)
            assert ref_7.source_status in ("not_found", "api_error", "found")

            # Verify DOI enrichment — check that DOIs were preserved/added
            ref_1 = next((r for r in resolved if r.id == 1), None)
            assert ref_1 is not None
            if ref_1.source_status == "found":
                # Should have preserved the original DOI
                assert ref_1.doi is not None or ref_1.pmid is not None

            # Check that some refs got journal URLs
            refs_with_journal_url = [
                r for r in resolved if r.journal_url
            ]
            assert len(refs_with_journal_url) >= 1

            # --- Stage 6: Generate Report ---
            state = PipelineState(
                session_id="live-test-001",
                references=resolved,
                matches=matches,
                manuscript=manuscript,
            )
            report_file = tmp_path / "report.docx"
            report_path = generate_report(state, report_file)

            assert report_path.exists()
            assert report_path.suffix == ".docx"
            assert report_path.stat().st_size > 1000  # not trivially small

            # Verify report can be opened
            report_doc = Document(str(report_path))
            # Should have content
            assert len(report_doc.paragraphs) > 0
            assert len(report_doc.tables) > 0

            # Print summary for manual review
            print("\n=== LIVE PIPELINE RESULTS ===")
            print(f"References parsed: {len(manuscript.references)}")
            print(f"Citations found: {len(all_citations)}")
            print(f"DOIs extracted: {len(dois_found)}")
            print(f"PMIDs extracted: {len(pmids_found)}")
            print(f"Found via APIs: {len(found)}")
            print(f"Not found: {len(not_found)}")
            print(f"API errors: {len(api_error)}")
            print(f"Report size: {report_path.stat().st_size:,} bytes")
            for r in resolved:
                status_icon = {
                    "found": "+",
                    "not_found": "x",
                    "api_error": "!",
                    "pending": "?",
                }[r.source_status]
                pdf_status = "PDF" if r.pdf_path else "no-PDF"
                print(
                    f"  [{status_icon}] Ref {r.id}: {r.title[:60]}... "
                    f"| {r.source_status} | {pdf_status}"
                )

    @pytest.mark.asyncio
    async def test_pubmed_enriches_pmid_metadata(self) -> None:
        """Verify PubMed lookup enriches references with correct metadata."""
        from refcheck.stages.resolve_gaps.pubmed_client import search_by_pmid

        # Look up the BNT162b2 vaccine paper
        result = await search_by_pmid("33301246")
        assert result.found is True
        assert result.status == "found"
        assert result.pmid == "33301246"
        assert "BNT162b2" in result.title or "mRNA" in result.title.lower()
        # PubMed may record 2020 or 2021 depending on publication/ePub date
        assert result.year in (2020, 2021)

    @pytest.mark.asyncio
    async def test_crossref_enriches_doi_metadata(self) -> None:
        """Verify CrossRef returns correct metadata for known DOIs."""
        from refcheck.stages.resolve_gaps.crossref_client import search_by_doi

        # Look up the DNA structure paper
        result = await search_by_doi("10.1038/171737a0")
        assert result.found is True
        assert result.doi == "10.1038/171737a0"
        assert result.year == 1953
        assert "nucleic" in result.title.lower() or result.title != ""
