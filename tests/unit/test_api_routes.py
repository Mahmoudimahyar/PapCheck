"""Unit tests for FastAPI routes."""

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from refcheck.api.main import app

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
        # Create a minimal DOCX file
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
