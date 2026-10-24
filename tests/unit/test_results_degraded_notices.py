"""Results / session API: the run's degraded-mode notices (V5.8 G1, Results page banner)."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from refcheck.api.main import app
from refcheck.api.routes import sessions as sessions_route
from refcheck.api.routes.results_builders import build_summary, degraded_notices
from refcheck.api.routes.sessions import session_dir_of
from refcheck.db.converters import claim_to_db, verification_to_db
from refcheck.db.deps import get_db
from refcheck.db.models import SessionDB
from refcheck.llm import degradation
from refcheck.models.claim import Claim
from refcheck.models.verification import VerificationResult

_SID = "sess_degraded"
_CREDITS = "Add credits to the OpenAI account (or set a key with credit), then re-run."


def _billing(role: str, mode: degradation.Mode,
             fallback: str | None = None) -> degradation.Degradation:
    return degradation.build(role, mode, kind="billing", provider="openai",
                             reason="billing: insufficient_quota", fallback_model=fallback)


def _save_openai_outage(session_dir: Path) -> None:
    """What a run on an OpenAI account without credits saves (file order != pipeline)."""
    session_dir.mkdir(parents=True, exist_ok=True)
    degradation.save(session_dir / degradation.RUN_FILE, {
        "confirm": _billing("confirm", "fallback", "claude-sonnet-5-5"),
        "screen": _billing("screen", "skipped"),
        "embedding": _billing("embedding", "bm25_only"),
    })


class TestDegradedNotices:
    def test_one_sentence_per_role_in_pipeline_order_then_the_fix_once(
            self, tmp_path: Path) -> None:
        _save_openai_outage(tmp_path)
        notices = degraded_notices(tmp_path)
        assert len(notices) == 4
        assert [n.split(":", 1)[0] for n in notices[:3]] == ["screen", "embedding", "confirm"]
        assert notices[3] == _CREDITS
        assert sum(_CREDITS in n for n in notices) == 1
        assert "BM25" in notices[1]
        assert "claude-sonnet-5-5" in notices[2] and "human review" in notices[2]

    def test_each_distinct_fix_is_kept(self, tmp_path: Path) -> None:
        budget = degradation.build("confirm", "unavailable", kind="budget", provider="anthropic")
        degradation.save(tmp_path / degradation.RUN_FILE,
                         {"screen": _billing("screen", "skipped"), "confirm": budget})
        notices = degraded_notices(tmp_path)
        assert notices[2:] == [_CREDITS, budget.action]

    def test_transient_role_has_no_fix_line(self, tmp_path: Path) -> None:
        item = degradation.build("screen", "skipped", kind="rate_limit", provider="openai")
        degradation.save(tmp_path / degradation.RUN_FILE,
                         {"screen": item.model_copy(update={"failures": 3})})
        assert degraded_notices(tmp_path) == [degradation.describe(
            item.model_copy(update={"failures": 3}))]

    def test_absent_or_unreadable_file_means_no_notices(self, tmp_path: Path) -> None:
        assert degraded_notices(tmp_path) == []
        assert degraded_notices(tmp_path / "missing_session") == []
        (tmp_path / degradation.RUN_FILE).write_text("not json", encoding="utf-8")
        assert degraded_notices(tmp_path) == []

    def test_summary_without_a_session_dir_has_none(self, tmp_path: Path) -> None:
        _save_openai_outage(tmp_path)
        assert build_summary([]).degraded_notices == []
        assert len(build_summary([], tmp_path).degraded_notices) == 4


@pytest.fixture
def base_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(sessions_route, "_BASE_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def client(base_dir: Path) -> Iterator[TestClient]:
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(SessionDB(id=_SID, manuscript_filename="m.docx", status="complete"))
        db.add(claim_to_db(Claim(id=1, extracted_claim="A claim", reference_ids=[1]), _SID))
        db.add(verification_to_db(VerificationResult(
            claim_id=1, reference_id=1, verdict="supported", confidence=0.9), _SID))
        db.commit()

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


class TestApi:
    def test_results_summary_carries_the_notices(self, client: TestClient,
                                                 base_dir: Path) -> None:
        _save_openai_outage(base_dir / _SID)
        summary = client.get(f"/api/sessions/{_SID}/results").json()["summary"]
        assert summary["degraded_notices"] == degraded_notices(base_dir / _SID)
        assert summary["supported"] == 1

    def test_session_detail_carries_the_notices(self, client: TestClient,
                                                base_dir: Path) -> None:
        _save_openai_outage(base_dir / _SID)
        body = client.get(f"/api/sessions/{_SID}").json()
        assert body["status"] == "complete"
        assert body["degraded_notices"][-1] == _CREDITS

    def test_normal_run_has_an_empty_list(self, client: TestClient) -> None:
        assert client.get(f"/api/sessions/{_SID}/results").json()[
            "summary"]["degraded_notices"] == []
        assert client.get(f"/api/sessions/{_SID}").json()["degraded_notices"] == []


class TestSessionIdIsNotAPath:
    """An id that leaves the sessions folder reads nothing (no path traversal)."""

    def test_only_a_folder_directly_inside_the_sessions_folder(self, base_dir: Path) -> None:
        assert session_dir_of(_SID) == (base_dir / _SID).resolve()
        for sid in ("..", ".", str(Path("..", "outside")), str(base_dir.parent / "outside")):
            assert session_dir_of(sid) is None, sid
        assert degraded_notices(session_dir_of("..")) == []

    def test_results_route_reads_no_notes_outside_it(
            self, client: TestClient, base_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sessions_route, "_BASE_DIR", base_dir / "sessions")
        _save_openai_outage(base_dir)  # what ".." names
        _save_openai_outage(base_dir / "outside")  # what "..\outside" names (Windows)
        for sid in ("%2E%2E", "..%5Coutside"):
            res = client.get(f"/api/sessions/{sid}/results")
            assert res.status_code == 200, sid
            assert res.json()["summary"]["degraded_notices"] == [], sid
