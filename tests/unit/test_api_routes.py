"""Unit tests for FastAPI routes (V3 — database backend)."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from refcheck.api.main import app
from refcheck.db import engine as engine_mod
from refcheck.db.deps import get_db
from refcheck.db.models import (
    ClaimDB,
    PipelineEventDB,
    ReferenceDB,
    SessionDB,
    VerificationDB,
)

# Create a single in-memory engine for this test module.
# StaticPool ensures all connections share the same in-memory database.
_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
SQLModel.metadata.create_all(_ENGINE)
engine_mod.set_engine(_ENGINE)


def _get_test_db():  # type: ignore[no-untyped-def]
    """Yield a test DB session from the shared in-memory engine."""
    with Session(_ENGINE) as s:
        yield s


app.dependency_overrides[get_db] = _get_test_db
client = TestClient(app)


def _wipe() -> None:
    """Delete all rows from all tables."""
    with Session(_ENGINE) as s:
        for model in [
            VerificationDB, ClaimDB, PipelineEventDB,
            ReferenceDB, SessionDB,
        ]:
            s.exec(model.__table__.delete())  # type: ignore[union-attr, arg-type]
        s.commit()


def _seed_session(sid: str) -> None:
    with Session(_ENGINE) as db:
        db.add(SessionDB(id=sid, manuscript_filename="test.docx"))
        db.commit()


def _seed_results(sid: str) -> None:
    with Session(_ENGINE) as db:
        if not db.get(SessionDB, sid):
            db.add(SessionDB(id=sid, manuscript_filename="test.docx"))
        for c in [
            ClaimDB(session_id=sid, claim_number=1,
                     extracted_claim="Claim 1", reference_ids_json="[1]",
                     claim_type="factual", priority="high"),
            ClaimDB(session_id=sid, claim_number=2,
                     extracted_claim="Claim 2", reference_ids_json="[2]",
                     claim_type="background", priority="low"),
            ClaimDB(session_id=sid, claim_number=3,
                     extracted_claim="Claim 3", reference_ids_json="[3]",
                     claim_type="contrast", priority="high"),
        ]:
            db.add(c)
        for v in [
            VerificationDB(session_id=sid, claim_id=1, reference_id=1,
                           verdict="supported", confidence=0.92),
            VerificationDB(session_id=sid, claim_id=2, reference_id=2,
                           verdict="cannot_verify", confidence=0.3),
            VerificationDB(session_id=sid, claim_id=3, reference_id=3,
                           verdict="contradicted", confidence=0.88),
        ]:
            db.add(v)
        db.commit()


class TestHealthEndpoint:
    def setup_method(self) -> None:
        _wipe()

    def test_health_returns_ok(self) -> None:
        r = client.get("/api/health")
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "ok"
        assert d["version"] == "3.0.0"
        assert d["database"] == "connected"


class TestSessionEndpoints:
    def setup_method(self) -> None:
        _wipe()

    def test_create_session(self, tmp_path: Path) -> None:
        import docx
        doc = docx.Document()
        doc.add_paragraph("Test")
        p = tmp_path / "test.docx"
        doc.save(str(p))
        with open(p, "rb") as f:
            r = client.post(
                "/api/sessions",
                files={"manuscript": ("test.docx", f)},
            )
        assert r.status_code == 201
        assert r.json()["id"].startswith("sess_")

    def test_create_session_invalid(self) -> None:
        r = client.post(
            "/api/sessions",
            files={"manuscript": ("t.txt", b"hi", "text/plain")},
        )
        assert r.status_code == 400

    def test_get_session_not_found(self) -> None:
        assert client.get("/api/sessions/bad").status_code == 404

    def test_get_session_found(self) -> None:
        _seed_session("sf")
        r = client.get("/api/sessions/sf")
        assert r.status_code == 200
        assert r.json()["id"] == "sf"

    def test_list_sessions(self) -> None:
        _seed_session("l1")
        _seed_session("l2")
        r = client.get("/api/sessions?page=1&per_page=10")
        assert r.json()["total"] >= 2

    def test_delete_session(self) -> None:
        _seed_session("del1")
        r = client.delete("/api/sessions/del1")
        assert r.status_code == 200
        assert client.get("/api/sessions/del1").status_code == 404

    def test_delete_session_not_found(self) -> None:
        assert client.delete("/api/sessions/nonexistent").status_code == 404


class TestReferenceEndpoints:
    def setup_method(self) -> None:
        _wipe()

    def test_list_empty(self) -> None:
        _seed_session("re")
        assert client.get("/api/sessions/re/references").json()["total"] == 0

    def test_list_with_data(self) -> None:
        _seed_session("rd")
        with Session(_ENGINE) as db:
            db.add(ReferenceDB(
                session_id="rd", ref_number=1,
                title="Test", source_status="found",
            ))
            db.commit()
        d = client.get("/api/sessions/rd/references").json()
        assert d["total"] == 1
        assert d["references"][0]["title"] == "Test"


class TestReportEndpoints:
    def setup_method(self) -> None:
        _wipe()

    def test_not_generated(self) -> None:
        _seed_session("nr")
        assert client.get("/api/sessions/nr/report").status_code == 404

    def test_preview_structure(self) -> None:
        _seed_results("ps")
        d = client.get("/api/sessions/ps/report/preview").json()
        assert d["summary"]["total"] == 3

    def test_preview_critical(self) -> None:
        _seed_results("pc")
        c = client.get("/api/sessions/pc/report/preview").json()
        assert len(c["critical_findings"]) == 1

    def test_preview_retracted(self) -> None:
        _seed_session("pr")
        with Session(_ENGINE) as db:
            db.add(ReferenceDB(
                session_id="pr", ref_number=1, title="R",
                retraction_status="retracted", retraction_detail="Fab",
            ))
            db.add(ReferenceDB(
                session_id="pr", ref_number=2, title="G",
                retraction_status="ok",
            ))
            db.commit()
        assert len(
            client.get("/api/sessions/pr/report/preview").json()["retracted"]
        ) == 1

    def test_preview_empty(self) -> None:
        _seed_session("pe")
        d = client.get("/api/sessions/pe/report/preview").json()
        assert d["summary"]["total"] == 0


class TestResultsEndpoint:
    def setup_method(self) -> None:
        _wipe()

    def test_summary(self) -> None:
        _seed_results("rs")
        s = client.get("/api/sessions/rs/results").json()["summary"]
        assert s["total"] == 3
        assert s["supported"] == 1

    def test_verdict_filter(self) -> None:
        _seed_results("rvf")
        r = client.get("/api/sessions/rvf/results?verdict=contradicted")
        assert len(r.json()["results"]) == 1

    def test_priority_filter(self) -> None:
        _seed_results("rpf")
        r = client.get("/api/sessions/rpf/results?priority=high")
        assert len(r.json()["results"]) == 2

    def test_confidence_filter(self) -> None:
        _seed_results("rcf")
        r = client.get("/api/sessions/rcf/results?min_confidence=0.5")
        assert len(r.json()["results"]) == 2

    def test_pagination(self) -> None:
        _seed_results("rpg")
        d = client.get("/api/sessions/rpg/results?per_page=1&page=1").json()
        assert len(d["results"]) == 1
        assert d["total"] == 3

    def test_empty(self) -> None:
        _seed_session("rem")
        assert client.get("/api/sessions/rem/results").json()["summary"]["total"] == 0


class TestOverrideEndpoint:
    def setup_method(self) -> None:
        _wipe()

    def test_override(self) -> None:
        _seed_results("o1")
        r = client.post(
            "/api/sessions/o1/results/1/override",
            json={"verdict": "supported", "reason": "ok"},
        )
        assert r.status_code == 200
        assert r.json()["verdict"] == "supported"

    def test_invalid_claim(self) -> None:
        _seed_results("o2")
        r = client.post(
            "/api/sessions/o2/results/999/override",
            json={"verdict": "supported", "reason": "t"},
        )
        assert r.status_code == 404

    def test_invalid_session(self) -> None:
        r = client.post(
            "/api/sessions/bad/results/1/override",
            json={"verdict": "supported", "reason": "t"},
        )
        assert r.status_code == 404


class TestClaimsEndpoints:
    def setup_method(self) -> None:
        _wipe()

    def test_list(self) -> None:
        _seed_results("cl")
        assert len(client.get("/api/sessions/cl/claims").json()) == 3

    def test_update(self) -> None:
        _seed_results("cu")
        r = client.put(
            "/api/sessions/cu/claims/1",
            json={"extracted_claim": "New", "priority": "low"},
        )
        assert r.status_code == 200
        assert r.json()["extracted_claim"] == "New"

    def test_delete(self) -> None:
        _seed_results("cd")
        client.delete("/api/sessions/cd/claims/1")
        assert len(client.get("/api/sessions/cd/claims").json()) == 2

    def test_update_nonexistent(self) -> None:
        _seed_results("cn")
        r = client.put(
            "/api/sessions/cn/claims/999",
            json={"extracted_claim": "t"},
        )
        assert r.status_code == 404
