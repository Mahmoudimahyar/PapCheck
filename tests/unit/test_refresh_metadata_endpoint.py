"""POST /references/{ref_id}/refresh-metadata (in-memory DB, HTTP mocked, re-verify mocked)."""

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from refcheck.api.main import app
from refcheck.db import engine as engine_mod
from refcheck.db.converters import claim_to_db, reference_to_db, verification_to_db
from refcheck.db.deps import get_db
from refcheck.db.models import SessionDB
from refcheck.db.reference_repo import get_reference
from refcheck.models.claim import Claim
from refcheck.models.reference import Reference
from refcheck.models.verification import VerificationResult

_DOI = "10.5555/synthetic.0001"
_STUB = "Synthetic stub abstract cut off after the first line of text, no more."
_FULL = " ".join([
    "Background: A synthetic gel was compared with saline in forty rats.",
    "Methods: Wounds were measured daily for two weeks by a blinded observer.",
    "Results: Closure was faster with the gel, and scar width fell by a third.",
    "Conclusions: Local delivery avoided systemic exposure to the drug entirely,",
    "and a larger study in a second species is now planned for next year.",
])
_OPENALEX = {
    "doi": f"https://doi.org/{_DOI}",
    "open_access": {"is_oa": True, "oa_status": "green", "oa_url": "https://repo.example/1"},
    "best_oa_location": {"pdf_url": None, "license": "cc-by-nc",
                         "version": "acceptedVersion", "landing_page_url": "https://repo.example/1"},
    "ids": {"pmcid": "https://www.ncbi.nlm.nih.gov/pmc/articles/1234567"},
}


@pytest.fixture(autouse=True)
def _no_disk_cache() -> Iterator[None]:
    with (
        patch("refcheck.stages.resolve_gaps.record_cache.get_cached_api_response",
              return_value=None),
        patch("refcheck.stages.resolve_gaps.record_cache.cache_api_response"),
    ):
        yield


@pytest.fixture
def engine() -> Iterator[object]:
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    previous = engine_mod._engine_instance
    engine_mod.set_engine(eng)
    yield eng
    engine_mod.set_engine(previous)


@pytest.fixture
def client(engine: object) -> Iterator[TestClient]:
    def _db() -> Iterator[Session]:
        with Session(engine) as s:  # type: ignore[arg-type]
            yield s

    app.dependency_overrides[get_db] = _db
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


def _seed(eng: object, abstract: str) -> None:
    def _v(cid: int, override: bool = False) -> VerificationResult:
        return VerificationResult(claim_id=cid, reference_id=10, verdict="cannot_verify",
                                  user_override=override)

    with Session(eng) as db:  # type: ignore[arg-type]
        db.add(SessionDB(id="s1", manuscript_filename="m.docx"))
        db.add(reference_to_db(Reference(
            id=10, title="Synthetic gel study", doi=_DOI, abstract_text=abstract,
            abstract_source="crossref", source_status="found"), "s1"))
        for cid, refs in ((1, [10]), (2, [10]), (3, [20])):
            db.add(claim_to_db(Claim(id=cid, extracted_claim=f"c{cid}", reference_ids=refs), "s1"))
        db.add(verification_to_db(_v(1), "s1"))
        db.add(verification_to_db(_v(2, override=True), "s1"))
        db.commit()


def _mock_http(
    handler: Callable[[httpx.Request], httpx.Response],
) -> AbstractContextManager[object]:
    return patch("refcheck.stages.resolve_gaps.metadata_refresh.new_client",
                 lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def _apis(openalex_status: int = 200) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host == "www.ebi.ac.uk":
            return httpx.Response(200, json={"resultList": {"result": [
                {"doi": _DOI, "abstractText": f"<p>{_FULL}</p>"}]}})
        if host == "api.openalex.org":
            return httpx.Response(openalex_status, json=_OPENALEX)
        if host == "api.semanticscholar.org":
            return httpx.Response(200, json=[None])
        return httpx.Response(200, json={"message": {"title": ["Synthetic gel study"]}})
    return handler


def test_new_abstract_and_hint_stored_and_reverified(
    client: TestClient, engine: object,
) -> None:
    _seed(engine, _STUB)
    task = MagicMock()
    with _mock_http(_apis()), patch("refcheck.api.routes.references.reverify_reference", task):
        resp = client.post("/api/sessions/s1/references/10/refresh-metadata")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["abstract_changed"] is True and data["abstract_source"] == "europepmc"
    assert data["previous_abstract_chars"] == len(_STUB)
    assert data["abstract_chars"] == len(_FULL)
    assert {"abstract_text", "oa_status", "oa_url", "pmc_id"} <= set(data["changed_fields"])
    assert data["open_access"]["oa_status"] == "green"
    assert data["claims_to_reverify"] == [1]  # claim 2 was overridden by the user
    assert task.call_args.args == ("s1", 10, [1])
    with Session(engine) as db:  # type: ignore[arg-type]
        row = get_reference(db, "s1", 10)
        assert row is not None
        assert (row.abstract_text, row.abstract_source) == (_FULL, "europepmc")
        assert (row.oa_status, row.oa_license, row.pmc_id) == ("green", "cc-by-nc", "PMC1234567")
    listed = client.get("/api/sessions/s1/references").json()["references"][0]
    assert listed["oa_url"] == "https://repo.example/1"
    assert listed["oa_version"] == "acceptedVersion"


def test_unchanged_abstract_does_not_reverify(client: TestClient, engine: object) -> None:
    _seed(engine, _FULL)
    task = MagicMock()
    with _mock_http(_apis(openalex_status=404)), \
            patch("refcheck.api.routes.references.reverify_reference", task):
        resp = client.post("/api/sessions/s1/references/10/refresh-metadata")
    data = resp.json()
    assert resp.status_code == 200
    assert data["changed_fields"] == [] and data["abstract_changed"] is False
    assert data["reverification_started"] is False
    task.assert_not_called()


def test_unknown_reference(client: TestClient, engine: object) -> None:
    _seed(engine, _STUB)
    resp = client.post("/api/sessions/s1/references/99/refresh-metadata")
    assert resp.status_code == 404
