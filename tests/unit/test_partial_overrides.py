"""A reviewer override changes only the verdict: stale partial fields are not shown.

The stored partial type, elements, action and guards explained the model's
verdict. Once a reviewer picks another verdict they are hidden in the API, the
breakdown and the report; a reviewer's "partially supported" is "unclassified".
"Cleared" guard notes belong to supported results only. Synthetic data only.
"""

from collections.abc import Iterator

import docx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from refcheck.api.main import app
from refcheck.db.converters import claim_to_db, reference_to_db, verification_to_db
from refcheck.db.deps import get_db
from refcheck.models.claim import Claim
from refcheck.models.reference import Reference
from refcheck.models.verification import VerificationResult
from refcheck.stages.generate_report.partial_detail import add_partial_lines
from refcheck.stages.generate_report.partial_findings import (
    UNCLASSIFIED,
    action_of,
    elements_of,
    guarded_results,
    guards_of,
    partial_key,
    partial_type_of,
    severity_of,
)

_TYPED = {"partial_type": "specific_detail_mismatch", "partial_severity": "major",
          "author_action": "Correct the specific ('12 weeks').",
          "unsupported_elements": ["12 weeks"]}


def _v(claim_id: int, verdict: str, **extra: object) -> VerificationResult:
    return VerificationResult.model_validate({
        "claim_id": claim_id, "reference_id": claim_id, "verdict": verdict,
        "confidence": 0.7, "reasoning": "Synthetic reasoning.", **extra})


def _reviewed(verdict: str, original: str, **extra: object) -> VerificationResult:
    return _v(1, verdict, user_override=True, original_verdict=original, **extra)


def test_reviewer_verdict_hides_the_model_classification() -> None:
    v = _reviewed("supported", "partially_supported", **_TYPED)
    assert partial_type_of(v) is None and elements_of(v) == []
    assert severity_of(v) is None and action_of(v) == "" and partial_key(v) is None


def test_reviewer_partial_verdict_is_unclassified() -> None:
    v = _reviewed("partially_supported", "not_supported", partial_type="tangential_source")
    assert partial_key(v) == UNCLASSIFIED and severity_of(v) is None


def test_same_verdict_after_review_keeps_the_classification() -> None:
    v = _reviewed("partially_supported", "partially_supported", **_TYPED)
    assert partial_key(v) == "specific_detail_mismatch" and severity_of(v) == "major"
    assert elements_of(v) == ["12 weeks"] and action_of(v) == _TYPED["author_action"]


def test_cannot_verify_shows_no_classification() -> None:
    v = _v(3, "cannot_verify", guards_applied=["cocited_share"], **_TYPED)
    assert partial_type_of(v) is None and elements_of(v) == [] and guards_of(v) == []
    assert severity_of(v) is None and action_of(v) == ""


def test_stale_guards_do_not_count_as_cleared() -> None:
    stale = _reviewed("not_supported", "supported", guards_applied=["cocited_share"])
    kept = _v(2, "supported", guards_applied=["cocited_share"])
    assert guards_of(stale) == [] and guarded_results([stale, kept]) == [kept]


def _report_text(result: VerificationResult) -> str:
    document = docx.Document()
    add_partial_lines(document, result)
    return "\n".join(p.text for p in document.paragraphs)


def test_report_lines_follow_the_shown_verdict() -> None:
    assert "Issue type" in _report_text(_v(1, "partially_supported", **_TYPED))
    assert _report_text(_reviewed("not_supported", "partially_supported", **_TYPED)) == ""
    partial_with_guard = _v(1, "partially_supported", guards_applied=["cocited_share"], **_TYPED)
    assert "Cleared" not in _report_text(partial_with_guard)
    assert "Cleared" in _report_text(_v(1, "supported", guards_applied=["cocited_share"]))


@pytest.fixture
def client() -> Iterator[TestClient]:
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(reference_to_db(Reference(id=1, title="Paper 1"), "s"))
        db.add(claim_to_db(Claim(id=1, extracted_claim="Synthetic claim", reference_ids=[1]), "s"))
        db.add(verification_to_db(_v(1, "partially_supported", **_TYPED), "s"))
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


def _override(client: TestClient, verdict: str) -> dict[str, object]:
    response = client.post("/api/sessions/s/results/1/override",
                           json={"verdict": verdict, "reason": "checked"})
    assert response.status_code == 200
    return dict(response.json())


def test_override_through_the_api(client: TestClient) -> None:
    item = _override(client, "supported")
    assert item["partial_type"] is None and item["unsupported_elements"] == []
    assert item["author_action"] == "" and item["partial_severity"] is None
    summary = client.get("/api/sessions/s/results").json()["summary"]
    assert summary["partial_types"]["specific_detail_mismatch"] == 0
    breakdown = client.get("/api/sessions/s/partial-breakdown").json()
    assert breakdown["total_partial"] == 0


def test_second_override_keeps_the_model_verdict_as_original(client: TestClient) -> None:
    _override(client, "supported")
    item = _override(client, "partially_supported")  # back to the model's verdict
    assert item["partial_type"] == "specific_detail_mismatch"
    diff = client.get("/api/sessions/s/report/diff").json()["changes"][0]
    assert diff["original_verdict"] == "partially_supported"
