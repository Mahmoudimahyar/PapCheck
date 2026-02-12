"""Unit tests for report generation."""

from pathlib import Path

import docx
import pytest

from refcheck.models.claim import Claim
from refcheck.models.pipeline import PipelineState
from refcheck.models.reference import ParsedManuscript, Reference
from refcheck.models.verification import VerificationResult
from refcheck.stages.generate_report import generate_report


def _make_state(
    refs: list[Reference] | None = None,
    claims: list[Claim] | None = None,
    verifications: list[VerificationResult] | None = None,
) -> PipelineState:
    """Create a pipeline state with optional data."""
    manuscript = ParsedManuscript(filename="test.docx")
    return PipelineState(
        session_id="test_session",
        manuscript=manuscript,
        references=refs or [],
        claims=claims or [],
        verification_results=verifications or [],
    )


class TestReporter:
    def test_rg01_generates_valid_docx(self, tmp_path: Path) -> None:
        """RG-01: Report generates a valid DOCX file."""
        refs = [
            Reference(id=1, title="Found Paper", source_status="found"),
            Reference(id=2, title="Not Found Paper", source_status="not_found"),
        ]
        state = _make_state(refs)
        output = tmp_path / "report.docx"

        result = generate_report(state, output)
        assert result.exists()
        doc = docx.Document(str(result))
        assert len(doc.paragraphs) > 0

    def test_rg02_summary_counts_match(self, tmp_path: Path) -> None:
        """RG-02: Summary counts match input data."""
        refs = [
            Reference(id=1, title="Paper 1", source_status="found"),
            Reference(id=2, title="Paper 2", source_status="found"),
            Reference(id=3, title="Paper 3", source_status="not_found"),
            Reference(id=4, title="Paper 4", source_status="api_error"),
        ]
        state = _make_state(refs)
        output = tmp_path / "report.docx"

        generate_report(state, output)
        doc = docx.Document(str(output))
        full_text = "\n".join(p.text for p in doc.paragraphs)

        assert "Total references: 4" in full_text
        assert "Found in databases: 2" in full_text
        assert "Not found: 1" in full_text
        assert "API errors: 1" in full_text

    def test_rg04_empty_results(self, tmp_path: Path) -> None:
        """RG-04: Empty results produce a valid report."""
        state = _make_state([])
        output = tmp_path / "report.docx"

        result = generate_report(state, output)
        assert result.exists()
        doc = docx.Document(str(result))
        assert len(doc.paragraphs) > 0

    def test_rg05_large_report(self, tmp_path: Path) -> None:
        """RG-05: 150 references generates in reasonable time."""
        import time

        refs = [
            Reference(
                id=i,
                title=f"Paper {i}: A Study of Topic {i}",
                authors=[f"Author{i} A", f"Author{i} B"],
                source_status="found" if i % 3 != 0 else "not_found",
            )
            for i in range(1, 151)
        ]
        state = _make_state(refs)
        output = tmp_path / "report.docx"

        start = time.time()
        result = generate_report(state, output)
        elapsed = time.time() - start

        assert result.exists()
        assert elapsed < 60

    def test_not_found_section(self, tmp_path: Path) -> None:
        """Not-found section lists unfound references."""
        refs = [
            Reference(
                id=1, title="Missing Paper", source_status="not_found",
                doi="10.1234/missing",
            ),
        ]
        state = _make_state(refs)
        output = tmp_path / "report.docx"

        generate_report(state, output)
        doc = docx.Document(str(output))
        full_text = "\n".join(p.text for p in doc.paragraphs)
        assert "Missing Paper" in full_text

    # --- V1 report tests ---

    def test_v1_report_includes_critical_findings(self, tmp_path: Path) -> None:
        """V1 report with verification results includes Critical Findings."""
        refs = [Reference(id=1, title="Paper 1", source_status="found")]
        claims = [Claim(id=1, extracted_claim="Drug X works", reference_ids=[1])]
        verifications = [
            VerificationResult(
                claim_id=1, reference_id=1, verdict="contradicted",
                confidence=0.9, reasoning="Source says otherwise",
            ),
        ]
        state = _make_state(refs, claims, verifications)
        output = tmp_path / "report.docx"

        generate_report(state, output)
        doc = docx.Document(str(output))
        full_text = "\n".join(p.text for p in doc.paragraphs)
        assert "Critical Findings" in full_text
        assert "CONTRADICTED" in full_text

    def test_v1_report_all_supported(self, tmp_path: Path) -> None:
        """V1 report with all supported shows verified section."""
        refs = [Reference(id=1, title="Paper 1", source_status="found")]
        claims = [Claim(id=1, extracted_claim="Claim 1", reference_ids=[1])]
        verifications = [
            VerificationResult(
                claim_id=1, reference_id=1, verdict="supported",
                confidence=0.95,
            ),
        ]
        state = _make_state(refs, claims, verifications)
        output = tmp_path / "report.docx"

        generate_report(state, output)
        doc = docx.Document(str(output))
        full_text = "\n".join(p.text for p in doc.paragraphs)
        assert "Verified References" in full_text
        assert "1 claims verified as supported" in full_text

    def test_v1_report_mixed_verdicts(self, tmp_path: Path) -> None:
        """V1 report with mixed verdicts has correct counts."""
        refs = [
            Reference(id=i, title=f"Paper {i}", source_status="found")
            for i in range(1, 4)
        ]
        claims = [
            Claim(id=i, extracted_claim=f"Claim {i}", reference_ids=[i])
            for i in range(1, 4)
        ]
        verifications = [
            VerificationResult(claim_id=1, reference_id=1, verdict="supported", confidence=0.9),
            VerificationResult(claim_id=2, reference_id=2, verdict="contradicted", confidence=0.8),
            VerificationResult(claim_id=3, reference_id=3, verdict="partially_supported", confidence=0.6),
        ]
        state = _make_state(refs, claims, verifications)
        output = tmp_path / "report.docx"

        generate_report(state, output)
        doc = docx.Document(str(output))
        full_text = "\n".join(p.text for p in doc.paragraphs)
        assert "Supported: 1" in full_text
        assert "Contradicted: 1" in full_text
        assert "Partially supported: 1" in full_text

    def test_v1_fallback_to_existence_report(self, tmp_path: Path) -> None:
        """Without verifications, falls back to existence-only report."""
        refs = [Reference(id=1, title="Paper 1", source_status="found")]
        state = _make_state(refs)
        output = tmp_path / "report.docx"

        generate_report(state, output)
        doc = docx.Document(str(output))
        full_text = "\n".join(p.text for p in doc.paragraphs)
        assert "Existence Report" in full_text
        assert "Executive Summary" not in full_text

    def test_v1_methodology_note(self, tmp_path: Path) -> None:
        """V1 report includes methodology note with model name."""
        refs = [Reference(id=1, title="Paper 1", source_status="found")]
        verifications = [
            VerificationResult(claim_id=1, reference_id=1, verdict="supported"),
        ]
        state = _make_state(refs, verifications=verifications)
        output = tmp_path / "report.docx"

        generate_report(state, output)
        doc = docx.Document(str(output))
        full_text = "\n".join(p.text for p in doc.paragraphs)
        assert "Methodology Note" in full_text
        assert "Claude Sonnet" in full_text
