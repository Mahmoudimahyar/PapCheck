"""/api/health: per-role model status, Decisions API status, deep preflight."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from refcheck.api.main import app
from refcheck.api.routes.health import RoleHealth, decisions_status, llm_overall
from refcheck.db.deps import get_db
from refcheck.llm import keys
from refcheck.llm.roles import RoleStatus, mark_unavailable
from tests.unit.llm_fakes import isolated_llm_env

_ROLES = {"screen", "verifier", "judge", "confirm", "adjudicator", "utility", "embedding"}


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    yield from isolated_llm_env(monkeypatch, tmp_path)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    # No GROBID in unit tests: skip the 3 s connection attempt.
    monkeypatch.setattr("refcheck.api.routes.health._check_grobid",
                        AsyncMock(return_value="unavailable"))
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    def _db() -> Iterator[Session]:
        with Session(engine) as s:
            yield s

    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _db
    yield TestClient(app)
    if previous is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous


def _health(model_id: str | None, available: bool, enabled: bool = True) -> RoleHealth:
    return RoleHealth(role="x", model_id=model_id, available=available, enabled=enabled)


class TestStaticHealth:
    def test_reports_every_role(self, client: TestClient) -> None:
        data = client.get("/api/health").json()
        assert data["status"] == "ok" and data["database"] == "connected"
        assert set(data["models"]) == _ROLES
        assert data["models"]["judge"]["model_id"] == "claude-sonnet-5-5"
        assert data["models"]["verifier"]["model_id"] == "claude-haiku-5-5"
        assert data["models"]["confirm"]["model_id"] == "gpt-6-luna"
        assert data["models"]["screen"]["display_name"] == "Decisions API · gpt-6-luna"
        assert data["llm"] == "ok" and data["decisions_api"] == "available"
        assert data["privacy_profile"] == "standard" and data["deep"] is False

    def test_fallback_and_last_error(self, client: TestClient) -> None:
        mark_unavailable("claude-sonnet-5-5", "billing: credit balance too low")
        judge = client.get("/api/health").json()["models"]["judge"]
        assert judge["model_id"] == "gpt-6.1-sol" and judge["fallback_index"] == 1
        assert judge["available"] is True

    def test_dead_verifier_is_unavailable(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("REFCHECK_VERIFIER_MODEL", "claude-opus-5-5")
        mark_unavailable("claude-opus-5-5", "auth: invalid key")
        data = client.get("/api/health").json()
        verifier = data["models"]["verifier"]
        assert verifier["available"] is False and "invalid key" in verifier["last_error"]
        assert data["llm"] == "unavailable"

    def test_openai_without_credits_degrades(self, client: TestClient) -> None:
        keys.rotate("openai", reason="billing")  # the only OpenAI key: insufficient_quota
        data = client.get("/api/health").json()
        assert data["llm"] == "degraded" and data["decisions_api"] == "unavailable"
        confirm = data["models"]["confirm"]
        assert confirm["model_id"] == "claude-sonnet-5-5" and confirm["available"] is True
        assert confirm["degraded"] and confirm["degraded_mode"] == "fallback"
        assert confirm["cause"] == "billing" and confirm["persistent"] is True
        assert "same model family" in confirm["effect"]
        assert data["models"]["screen"]["degraded_mode"] == "skipped"
        assert data["models"]["embedding"]["degraded_mode"] == "bm25_only"
        assert data["actions"] == [
            "Add credits to the OpenAI account (or set a key with credit), then re-run."]
        assert len(data["degraded_notices"]) == 3
        assert any("BM25" in n for n in data["degraded_notices"])

    def test_screen_disabled(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REFCHECK_SCREEN_ENABLED", "false")
        data = client.get("/api/health").json()
        assert data["decisions_api"] == "disabled" and data["llm"] == "ok"
        assert data["models"]["screen"]["enabled"] is False

    def test_broken_llm_layer_still_answers(self, client: TestClient) -> None:
        with patch("refcheck.api.routes.health_llm.role_status",
                   side_effect=RuntimeError("boom")):
            data = client.get("/api/health").json()
        assert data["status"] == "ok" and data["models"] == {} and data["llm"] == "unknown"


class TestDeepHealth:
    def test_deep_runs_preflight(self, client: TestClient) -> None:
        probed = {"verifier": RoleStatus(role="verifier", model_id="gpt-6-luna", available=True,
                                         candidates=["gpt-6-luna"], probed=True, probe_ok=True,
                                         latency_ms=420)}
        with patch("refcheck.llm.health.preflight", AsyncMock(return_value=probed)) as pf:
            data = client.get("/api/health?deep=true").json()
        pf.assert_awaited_once()
        assert data["deep"] is True
        assert data["models"]["verifier"]["probe_ok"] is True
        assert data["models"]["verifier"]["latency_ms"] == 420
        assert data["decisions_api"] == "unknown"


class TestHelpers:
    def test_llm_overall(self) -> None:
        ok = _health("m", True)
        assert llm_overall({}) == "unknown"
        assert llm_overall({"verifier": ok, "judge": ok, "confirm": ok}) == "ok"
        assert llm_overall({"verifier": ok, "utility": _health(None, False)}) == "degraded"
        # V5.8: only the verifier is required; a dead judge / confirm degrades.
        assert llm_overall({"verifier": _health(None, False)}) == "unavailable"
        assert llm_overall({"judge": _health(None, False)}) == "degraded"
        fallback = _health("claude-sonnet-5-5", True).model_copy(update={"degraded": True})
        assert llm_overall({"verifier": ok, "confirm": fallback}) == "degraded"
        assert llm_overall({"screen": _health(None, False, enabled=False)}) == "ok"

    def test_decisions_status(self) -> None:
        assert decisions_status(None) == "unknown"
        assert decisions_status(_health("d", True)) == "available"
        assert decisions_status(_health(None, False)) == "unavailable"
        assert decisions_status(_health(None, False, enabled=False)) == "disabled"
