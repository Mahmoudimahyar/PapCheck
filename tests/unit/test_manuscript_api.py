"""Tests for manuscript viewer API endpoints."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from refcheck.api.main import app
from refcheck.db.deps import get_db
from refcheck.db.models import (
    ClaimDB,
    ReferenceDB,
    SessionDB,
    VerificationDB,
)

# Each test class gets a fresh engine via fixtures
# to avoid cross-contamination with other test modules.


@pytest.fixture(autouse=True)
def _setup_db():
    """Create a fresh in-memory DB for each test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    def _get_db():  # type: ignore[no-untyped-def]
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_db] = _get_db

    # Expose the engine for seeding
    _setup_db.engine = engine  # type: ignore[attr-defined]
    yield engine
    app.dependency_overrides.pop(get_db, None)


def _engine():  # type: ignore[no-untyped-def]
    """Get the current test engine."""
    return _setup_db.engine  # type: ignore[attr-defined]


def _seed_session(sid: str = "sess_test") -> None:
    with Session(_engine()) as db:
        db.add(SessionDB(id=sid, status="complete", manuscript_filename="t.docx"))
        db.commit()


def _seed_claim(
    sid: str, claim_num: int, text: str = "",
    location_json: str | None = None,
) -> None:
    with Session(_engine()) as db:
        db.add(ClaimDB(
            session_id=sid, claim_number=claim_num,
            manuscript_text=text, extracted_claim=text,
            claim_type="factual", priority="high",
            reference_ids_json=json.dumps([1]),
            location_json=location_json,
        ))
        db.commit()


def _seed_verification(
    sid: str, claim_id: int,
    verdict: str = "supported", confidence: float = 0.9,
    evidence_sections_json: str | None = None,
) -> None:
    with Session(_engine()) as db:
        db.add(VerificationDB(
            session_id=sid, claim_id=claim_id, reference_id=1,
            verdict=verdict, confidence=confidence,
            evidence_quotes_json="[]", reasoning="Test reasoning",
            evidence_sections_json=evidence_sections_json,
        ))
        db.commit()


def _seed_reference(sid: str, ref_num: int = 1) -> None:
    with Session(_engine()) as db:
        db.add(ReferenceDB(
            session_id=sid, ref_number=ref_num,
            title="Test Reference", authors_json='["Smith A"]',
        ))
        db.commit()


def _make_loc(para_idx: int, start: int, end: int) -> str:
    return json.dumps({
        "paragraph_index": para_idx, "char_start": start,
        "char_end": end, "citation_markers": ["1"],
        "section_heading": "Results", "in_figure_or_table": False,
    })


class TestGetManuscript:
    def test_returns_claims_with_positions(self) -> None:
        """VA-01: GET manuscript returns paragraphs with claim positions."""
        _seed_session()
        _seed_claim("sess_test", 1, "Drug X reduces mortality", _make_loc(0, 0, 30))
        _seed_verification("sess_test", 1, "supported", 0.9)

        with TestClient(app) as c:
            resp = c.get("/api/sessions/sess_test/manuscript")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_claims"] == 1
        assert "supported" in data["legend"]

    def test_claim_no_verification_pending(self) -> None:
        """VA-04: Claim with no verification → verdict = 'pending'."""
        _seed_session()
        _seed_claim("sess_test", 1, "Some claim", _make_loc(0, 0, 20))

        with TestClient(app) as c:
            resp = c.get("/api/sessions/sess_test/manuscript")
        assert resp.status_code == 200
        data = resp.json()
        assert "pending" in data["legend"]

    def test_claim_no_location_unmapped(self) -> None:
        """VA-05: Claim with no location → appears in unmapped list."""
        _seed_session()
        _seed_claim("sess_test", 1, "Unmapped claim")

        with TestClient(app) as c:
            resp = c.get("/api/sessions/sess_test/manuscript")
        data = resp.json()
        assert 1 in data["unmapped_claims"]

    def test_legend_counts_match(self) -> None:
        """VA-06: Legend counts match actual verdict distribution."""
        _seed_session()
        for i in range(1, 4):
            _seed_claim("sess_test", i, f"Claim {i}", _make_loc(i, 0, 10))
        _seed_verification("sess_test", 1, "supported")
        _seed_verification("sess_test", 2, "supported")
        _seed_verification("sess_test", 3, "contradicted")

        with TestClient(app) as c:
            resp = c.get("/api/sessions/sess_test/manuscript")
        data = resp.json()
        assert data["legend"]["supported"] == 2
        assert data["legend"]["contradicted"] == 1


class TestGetEvidence:
    def test_returns_evidence_sections(self) -> None:
        """VA-02: GET evidence returns sections with quote highlights."""
        _seed_session()
        _seed_claim("sess_test", 1, "Drug X reduces mortality")
        _seed_reference("sess_test", 1)
        ev_json = json.dumps([{
            "section_heading": "Results",
            "full_text": "Drug X resulted in 28% reduction.",
            "page_number": None,
            "quote_highlights": [{
                "quote": "28% reduction",
                "char_start": 19, "char_end": 32,
                "match_type": "numeric_mismatch",
                "manuscript_element": "",
            }],
        }])
        _seed_verification("sess_test", 1, "partially_supported", 0.75, ev_json)

        with TestClient(app) as c:
            resp = c.get("/api/sessions/sess_test/evidence/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["claim"]["id"] == 1
        assert len(data["verifications"]) == 1
        v = data["verifications"][0]
        assert v["verdict"] == "partially_supported"
        assert len(v["evidence_sections"]) == 1
        hl = v["evidence_sections"][0]["quote_highlights"][0]
        assert hl["match_type"] == "numeric_mismatch"

    def test_404_invalid_claim(self) -> None:
        """VA-07: 404 for invalid claim ID."""
        _seed_session()

        with TestClient(app) as c:
            resp = c.get("/api/sessions/sess_test/evidence/999")
        assert resp.status_code == 404
