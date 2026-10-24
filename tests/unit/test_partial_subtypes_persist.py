"""V5.4 partial sub-types end to end (offline): a genuine partial survives the DB, is
returned by the results API and is listed under its DOCX report sub-section.

Scripted LLM answers: partial_e2e_fakes. Synthetic manuscript and sources only.
"""

from collections.abc import Iterator
from pathlib import Path

import docx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from refcheck.api.main import app
from refcheck.db.converters import (
    claim_to_db,
    db_to_verification,
    reference_to_db,
    verification_to_db,
)
from refcheck.db.deps import get_db
from refcheck.db.models import VerificationDB
from refcheck.models.partial_types import GUARD_LABELS, PARTIAL_TYPE_INFO, author_action
from refcheck.models.pipeline import PipelineState
from refcheck.models.reference import ParsedManuscript, Reference
from refcheck.models.verification import VerificationResult
from refcheck.stages.generate_report import generate_report
from refcheck.stages.generate_report.partial_sections import GUARDED_HEADING, PARTIAL_HEADING
from tests.unit.partial_e2e_fakes import (
    SCOPE,
    RunResult,
    ScriptedFakes,
    claims,
    run_all,
    scripted,
)


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> Iterator[ScriptedFakes]:
    with scripted(monkeypatch) as f:
        yield f


@pytest.fixture
async def run(fakes: ScriptedFakes, tmp_path: Path) -> RunResult:
    return await run_all(fakes, tmp_path)


def _persist(refs: list[Reference], results: list[VerificationResult]) -> Session:
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    db = Session(engine)
    db.add_all([reference_to_db(r, "s") for r in refs])
    db.add_all([claim_to_db(c, "s") for c in claims()])
    db.add_all([verification_to_db(v, "s") for v in results])
    db.commit()
    return db


async def test_genuine_partial_persists_to_api_and_report(
    run: RunResult, tmp_path: Path,
) -> None:
    _, refs, results = run
    action = author_action("scope_overgeneralized", SCOPE)
    c = results[4]
    assert (c.verdict, c.partial_type, c.partial_severity) == (
        "partially_supported", "scope_overgeneralized", "major")
    assert c.author_action == action and c.unsupported_elements == [SCOPE]

    db = _persist(refs, list(results.values()))
    stored = {v.reference_id: v for v in map(db_to_verification,
                                             db.exec(select(VerificationDB)).all())}
    assert stored[4].partial_type == "scope_overgeneralized"
    assert stored[4].author_action == action and stored[1].guards_applied == ["evidence_recheck"]

    def _db() -> Iterator[Session]:
        yield db

    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _db
    try:
        client = TestClient(app)
        data = client.get("/api/sessions/s/results?partial_type=scope_overgeneralized").json()
        guarded = client.get("/api/sessions/s/results?partial_type=guarded").json()
    finally:
        app.dependency_overrides.pop(get_db, None)
        if previous is not None:
            app.dependency_overrides[get_db] = previous
    item = data["results"][0]
    assert data["total"] == 1 and item["claim_id"] == 4
    assert (item["partial_severity"], item["author_action"]) == ("major", action)
    assert data["summary"]["partial_types"]["scope_overgeneralized"] == 1
    assert sorted(r["claim_id"] for r in guarded["results"]) == [1, 2]

    state = PipelineState(session_id="s", manuscript=ParsedManuscript(filename="m.docx"),
                          references=refs, claims=claims(),
                          verification_results=list(stored.values()))
    document = docx.Document(str(generate_report(state, tmp_path / "report.docx")))
    text = "\n".join(p.text for p in document.paragraphs)
    label = PARTIAL_TYPE_INFO["scope_overgeneralized"][0]
    section = text[text.index(f"{label} (1)"):text.index("Verified References")]
    assert text.index(PARTIAL_HEADING) < text.index(f"{label} (1)")
    assert f"Issue type: {label} (major)" in section and f"What to do: {action}" in section
    assert f"Not stated in the source: {SCOPE}" in section
    guarded_text = text[text.index(GUARDED_HEADING):]
    for guard in ("evidence_recheck", "cocited_share"):
        assert f"{GUARD_LABELS[guard][0]} (1)" in guarded_text
