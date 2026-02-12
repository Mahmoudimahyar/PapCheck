"""Unit tests for FastAPI routes."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from refcheck.api.main import app
from refcheck.api.routes.references import get_reference_store
from refcheck.api.routes.results import get_claims_store, get_verification_store
from refcheck.models.claim import Claim
from refcheck.models.reference import Reference
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


class TestReportEndpoints:
    def test_report_not_generated(self) -> None:
        """GET /api/sessions/{id}/report returns 404 when no report."""
        response = client.get("/api/sessions/nonexistent/report")
        assert response.status_code == 404

    def test_preview_returns_structure(self) -> None:
        """GET preview returns correct structure."""
        _seed_results("test_preview_1")
        response = client.get("/api/sessions/test_preview_1/report/preview")
        assert response.status_code == 200
        data = response.json()
        assert "summary" in data
        assert "critical_findings" in data
        assert "minor_issues" in data
        assert "retracted" in data
        assert "overrides_count" in data
        assert "generated_at" in data
        assert data["summary"]["total"] == 3

    def test_preview_critical_findings(self) -> None:
        """Preview identifies contradicted claims as critical."""
        _seed_results("test_preview_2")
        response = client.get("/api/sessions/test_preview_2/report/preview")
        data = response.json()
        # Claim 3 is contradicted
        critical = data["critical_findings"]
        assert len(critical) == 1
        assert critical[0]["verdict"] == "contradicted"
        assert critical[0]["claim_id"] == "3"

    def test_preview_retracted_refs(self) -> None:
        """Preview lists retracted references."""
        ref_store = get_reference_store()
        ref_store["test_preview_3"] = [
            Reference(
                id=1,
                title="Retracted paper",
                retraction_status="retracted",
                retraction_detail="Fabricated data",
            ),
            Reference(id=2, title="Good paper", retraction_status="ok"),
        ]
        response = client.get("/api/sessions/test_preview_3/report/preview")
        data = response.json()
        assert len(data["retracted"]) == 1
        assert data["retracted"][0]["status"] == "retracted"

    def test_preview_empty_session(self) -> None:
        """Preview for session with no data returns empty structure."""
        response = client.get("/api/sessions/empty_preview/report/preview")
        data = response.json()
        assert data["summary"]["total"] == 0
        assert data["critical_findings"] == []
        assert data["overrides_count"] == 0


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


class TestOverrideEndpoint:
    def test_override_updates_verdict(self) -> None:
        """POST override changes verdict and stores original."""
        _seed_results("test_override_1")
        response = client.post(
            "/api/sessions/test_override_1/results/1/override",
            json={"verdict": "supported", "reason": "Manually verified in Table 3"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["verdict"] == "supported"

    def test_override_invalid_claim(self) -> None:
        """POST override with nonexistent claim returns 404."""
        _seed_results("test_override_2")
        response = client.post(
            "/api/sessions/test_override_2/results/999/override",
            json={"verdict": "supported", "reason": "test"},
        )
        assert response.status_code == 404

    def test_overridden_result_in_get(self) -> None:
        """Overridden result appears with user_override=True in GET."""
        _seed_results("test_override_3")
        client.post(
            "/api/sessions/test_override_3/results/3/override",
            json={"verdict": "supported", "reason": "Confirmed manually"},
        )
        response = client.get("/api/sessions/test_override_3/results")
        data = response.json()
        # Find the overridden result
        overridden = [r for r in data["results"] if r["claim_id"] == 3]
        assert len(overridden) == 1
        assert overridden[0]["verdict"] == "supported"

    def test_override_invalid_session(self) -> None:
        """POST override to nonexistent session returns 404."""
        response = client.post(
            "/api/sessions/nonexistent/results/1/override",
            json={"verdict": "supported", "reason": "test"},
        )
        assert response.status_code == 404


# --- V2 Claims API tests ---


class TestClaimsEndpoints:
    def test_get_claims_returns_list(self) -> None:
        """GET claims returns list of claims."""
        _seed_results("test_claims_1")
        response = client.get("/api/sessions/test_claims_1/claims")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3

    def test_update_claim(self) -> None:
        """PUT updates claim text and type."""
        _seed_results("test_claims_2")
        response = client.put(
            "/api/sessions/test_claims_2/claims/1",
            json={
                "extracted_claim": "Updated claim",
                "priority": "low",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["extracted_claim"] == "Updated claim"
        assert data["priority"] == "low"

    def test_delete_claim(self) -> None:
        """DELETE removes claim from list."""
        _seed_results("test_claims_3")
        response = client.delete(
            "/api/sessions/test_claims_3/claims/1",
        )
        assert response.status_code == 200
        # Verify it's gone
        response = client.get("/api/sessions/test_claims_3/claims")
        data = response.json()
        assert len(data) == 2
        assert all(c["id"] != 1 for c in data)

    def test_update_nonexistent_claim(self) -> None:
        """PUT to nonexistent claim returns 404."""
        _seed_results("test_claims_4")
        response = client.put(
            "/api/sessions/test_claims_4/claims/999",
            json={"extracted_claim": "test"},
        )
        assert response.status_code == 404
