"""Unit tests for FastAPI routes."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from refcheck.api.main import app
from refcheck.api.routes.results import get_claims_store, get_verification_store
from refcheck.models.claim import Claim
from refcheck.models.verification import VerificationResult

client = TestClient(app)


class TestHealthEndpoint:
    def test_health_returns_ok(self) -> None:
        """GET /api/health returns ok status."""
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["version"] == "0.1.0"


class TestSessionEndpoints:
    def test_create_session(self, tmp_path: Path) -> None:
        """POST /api/sessions creates a session."""
        import docx

        doc = docx.Document()
        doc.add_paragraph("Test")
        doc.add_heading("References", level=2)
        doc.add_paragraph("1. Smith J. Test paper. 2020.")
        docx_path = tmp_path / "test.docx"
        doc.save(str(docx_path))

        with open(docx_path, "rb") as f:
            response = client.post(
                "/api/sessions",
                files={"manuscript": ("test.docx", f, "application/octet-stream")},
            )
        assert response.status_code == 201
        data = response.json()
        assert data["id"].startswith("sess_")
        assert data["manuscript_filename"] == "test.docx"
        assert data["status"] == "created"

    def test_create_session_invalid_file(self) -> None:
        """POST /api/sessions rejects non-DOCX files."""
        response = client.post(
            "/api/sessions",
            files={"manuscript": ("test.txt", b"hello", "text/plain")},
        )
        assert response.status_code == 400

    def test_get_session_not_found(self) -> None:
        """GET /api/sessions/{id} returns 404 for unknown ID."""
        response = client.get("/api/sessions/nonexistent")
        assert response.status_code == 404


class TestReferenceEndpoints:
    def test_list_references_empty(self) -> None:
        """GET /api/sessions/{id}/references returns empty for unknown."""
        response = client.get("/api/sessions/nonexistent/references")
        assert response.status_code == 200
        data = response.json()
        assert data["references"] == []
        assert data["total"] == 0


class TestReportEndpoint:
    def test_report_not_generated(self) -> None:
        """GET /api/sessions/{id}/report returns 404 when no report."""
        response = client.get("/api/sessions/nonexistent/report")
        assert response.status_code == 404


# --- V1 Results API tests ---


def _seed_results(session_id: str) -> None:
    """Seed the in-memory stores with test data."""
    claims = [
        Claim(id=1, extracted_claim="Claim 1", reference_ids=[1], claim_type="factual", priority="high"),
        Claim(id=2, extracted_claim="Claim 2", reference_ids=[2], claim_type="background", priority="low"),
        Claim(id=3, extracted_claim="Claim 3", reference_ids=[3], claim_type="contrast", priority="high"),
    ]
    verifications = [
        VerificationResult(claim_id=1, reference_id=1, verdict="supported", confidence=0.92),
        VerificationResult(claim_id=2, reference_id=2, verdict="cannot_verify", confidence=0.3),
        VerificationResult(claim_id=3, reference_id=3, verdict="contradicted", confidence=0.88),
    ]
    get_claims_store()[session_id] = claims
    get_verification_store()[session_id] = verifications


class TestResultsEndpoint:
    def test_get_results_returns_summary(self) -> None:
        """GET results returns correct summary counts."""
        _seed_results("test_results_1")
        response = client.get("/api/sessions/test_results_1/results")
        assert response.status_code == 200
        data = response.json()
        summary = data["summary"]
        assert summary["total"] == 3
        assert summary["supported"] == 1
        assert summary["contradicted"] == 1
        assert summary["cannot_verify"] == 1

    def test_verdict_filter(self) -> None:
        """Verdict filter returns only matching results."""
        _seed_results("test_results_2")
        response = client.get(
            "/api/sessions/test_results_2/results?verdict=contradicted"
        )
        data = response.json()
        assert len(data["results"]) == 1
        assert data["results"][0]["verdict"] == "contradicted"

    def test_priority_filter(self) -> None:
        """Priority filter returns only matching results."""
        _seed_results("test_results_3")
        response = client.get(
            "/api/sessions/test_results_3/results?priority=high"
        )
        data = response.json()
        # Claims 1 and 3 are high priority
        assert len(data["results"]) == 2

    def test_min_confidence_filter(self) -> None:
        """Min confidence filter works."""
        _seed_results("test_results_4")
        response = client.get(
            "/api/sessions/test_results_4/results?min_confidence=0.5"
        )
        data = response.json()
        # Only claims 1 (0.92) and 3 (0.88) pass
        assert len(data["results"]) == 2

    def test_pagination(self) -> None:
        """Pagination works correctly."""
        _seed_results("test_results_5")
        response = client.get(
            "/api/sessions/test_results_5/results?per_page=1&page=1"
        )
        data = response.json()
        assert len(data["results"]) == 1
        assert data["total"] == 3
        assert data["page"] == 1
        assert data["per_page"] == 1

    def test_empty_results(self) -> None:
        """Empty results returns zero counts."""
        response = client.get("/api/sessions/empty_session/results")
        data = response.json()
        assert data["summary"]["total"] == 0
        assert data["results"] == []
        assert data["total"] == 0
