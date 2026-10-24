"""V5.4 partial sub-types through the API: item fields, summary counts, filter, breakdown.

Synthetic data, in-memory DB. Labels and actions come from models/partial_types.py.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from refcheck.api.main import app
from refcheck.db.converters import claim_to_db, reference_to_db, verification_to_db
from refcheck.db.deps import get_db
from refcheck.models.claim import Claim
from refcheck.models.partial_types import GUARD_ORDER, PARTIAL_TYPE_INFO, author_action
from refcheck.models.reference import Reference
from refcheck.models.verification import VerificationResult

_ACTION = "Correct or remove the specific ('12 weeks'), or cite the paper that reports it."


def _v(claim_id: int, verdict: str, **extra: object) -> VerificationResult:
    return VerificationResult.model_validate({
        "claim_id": claim_id, "reference_id": claim_id, "verdict": verdict,
        "confidence": 0.7, **extra})


def _verifications() -> list[VerificationResult]:
    return [
        _v(1, "partially_supported", partial_type="specific_detail_mismatch",
           partial_severity="major", author_action=_ACTION, unsupported_elements=["12 weeks"]),
        _v(2, "partially_supported", partial_type="missing_element",
           unsupported_elements=["and resorbs fast"]),
        _v(3, "partially_supported"),  # stored before V5.4: no type
        _v(4, "supported", guards_applied=["cocited_share"]),
        _v(5, "supported", guards_applied=["overliteral_wording", "evidence_recheck"]),
        _v(6, "supported"),
        _v(7, "not_supported", partial_type="tangential_source", partial_severity="major"),
        _v(8, "partially_supported", partial_type="coverage_limited", partial_severity="minor"),
    ]


@pytest.fixture
def client() -> Iterator[TestClient]:
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([reference_to_db(Reference(id=i, title=f"Paper {i}"), "s")
                    for i in range(1, 9)])
        db.add_all([claim_to_db(Claim(id=i, extracted_claim=f"Synthetic claim {i}",
                                      reference_ids=[i]), "s") for i in range(1, 9)])
        db.add_all([verification_to_db(v, "s") for v in _verifications()])
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


def _ids(client: TestClient, query: str) -> list[int]:
    data = client.get(f"/api/sessions/s/results?sort=ref_id&{query}").json()
    return [r["claim_id"] for r in data["results"]]


class TestResultItems:
    def test_fields_are_exposed(self, client: TestClient) -> None:
        items = {r["claim_id"]: r for r in client.get("/api/sessions/s/results").json()["results"]}
        first = items[1]
        assert first["partial_type"] == "specific_detail_mismatch"
        assert first["partial_severity"] == "major" and first["author_action"] == _ACTION
        assert first["unsupported_elements"] == ["12 weeks"]

    def test_missing_severity_and_action_come_from_the_taxonomy(self, client: TestClient) -> None:
        items = {r["claim_id"]: r for r in client.get("/api/sessions/s/results").json()["results"]}
        assert items[2]["partial_severity"] == "minor"
        assert items[2]["author_action"] == author_action("missing_element", "and resorbs fast")
        assert items[3]["partial_type"] is None and items[3]["author_action"] == ""
        assert items[5]["guards_applied"] == ["evidence_recheck", "overliteral_wording"]


class TestSummary:
    def test_counts_per_type_severity_and_guard(self, client: TestClient) -> None:
        summary = client.get("/api/sessions/s/results").json()["summary"]
        expected = dict.fromkeys(PARTIAL_TYPE_INFO, 0)
        expected.update(specific_detail_mismatch=1, missing_element=1, coverage_limited=1,
                        unclassified=1)
        assert summary["partial_types"] == expected
        assert list(summary["partial_types"])[:2] == ["specific_detail_mismatch",
                                                      "tangential_source"]
        assert summary["partial_severity"] == {"major": 1, "minor": 3}
        assert summary["guarded"] == 2
        assert summary["guards"] == {"evidence_recheck": 1, "cocited_share": 1,
                                     "overliteral_wording": 1}


class TestFilter:
    @pytest.mark.parametrize(("value", "ids"), [
        ("specific_detail_mismatch", [1]),
        ("unclassified", [3]),
        ("coverage_limited", [8]),
        ("tangential_source", []),  # only partial verdicts are grouped by type
        ("guarded", [4, 5]),
        ("guarded:cocited_share", [4]),
        ("guarded:evidence_recheck", [5]),
        ("all", list(range(1, 9))),
    ])
    def test_partial_type_filter(self, client: TestClient, value: str, ids: list[int]) -> None:
        assert _ids(client, f"partial_type={value}") == ids

    def test_combines_with_verdict_and_pages(self, client: TestClient) -> None:
        assert _ids(client, "partial_type=guarded&verdict=supported") == [4, 5]
        assert _ids(client, "partial_type=missing_element&verdict=supported") == []
        data = client.get("/api/sessions/s/results?sort=ref_id&partial_type=guarded"
                          "&per_page=1&page=2").json()
        assert data["total"] == 2 and [r["claim_id"] for r in data["results"]] == [5]


class TestBreakdownAndEvidence:
    def test_partial_breakdown_endpoint(self, client: TestClient) -> None:
        data = client.get("/api/sessions/s/partial-breakdown").json()
        assert data["total_partial"] == 4 and data["guarded"] == 2
        types = {t["type"]: t for t in data["types"]}
        assert [t["type"] for t in data["types"]] == [*PARTIAL_TYPE_INFO, "unclassified"]
        specifics = types["specific_detail_mismatch"]
        assert specifics["label"] == PARTIAL_TYPE_INFO["specific_detail_mismatch"][0]
        assert (specifics["count"], specifics["major"], specifics["minor"]) == (1, 1, 0)
        assert specifics["claim_ids"] == [1]
        assert specifics["author_action"] == author_action("specific_detail_mismatch")
        assert types["scope_overgeneralized"]["count"] == 0
        assert [g["guard"] for g in data["guards"]] == list(GUARD_ORDER)
        assert {g["guard"]: g["claim_ids"] for g in data["guards"]}["cocited_share"] == [4]

    def test_evidence_endpoint_carries_partial_fields(self, client: TestClient) -> None:
        evidence = client.get("/api/sessions/s/evidence/1").json()["verifications"][0]
        assert evidence["partial_type"] == "specific_detail_mismatch"
        assert evidence["author_action"] == _ACTION
        assert evidence["unsupported_elements"] == ["12 weeks"]

    def test_report_preview_rows_name_the_type(self, client: TestClient) -> None:
        rows = {r["claim_id"]: r for r in
                client.get("/api/sessions/s/report/preview").json()["minor_issues"]}
        assert rows["1"]["partial_label"] == "Wrong or missing specifics"
        assert rows["1"]["partial_severity"] == "major" and rows["1"]["author_action"] == _ACTION
        assert rows["3"]["partial_label"] == ""
