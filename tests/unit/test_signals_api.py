"""V5.2 signals through the API and the stage-complete messages (synthetic data, in-memory DB).

Regression for the V4.9 review: the API exposed only the whole sentence and the
final verdict, so the UI could not show what a reference is cited for, both
views of a dispute, incomplete sentences, ambiguous mappings or unusable PDFs.
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
from refcheck.models.reference import ParsedManuscript, Reference
from refcheck.models.verification import ModelReasoning, VerificationResult
from refcheck.services.stage_summaries import detect_summary, parse_summary, resolve_summary

_SENTENCE = "Gels lower IL-6 [1] and degrade within weeks [2]."


def _rows() -> tuple[list[Reference], list[Claim], list[VerificationResult]]:
    refs = [Reference(id=1, title="A", doi="10.1/a"),
            Reference(id=2, title="A", doi="10.1/A", duplicate_of=1),
            Reference(id=3, title="Other year", identity_status="mismatch")]
    claims = [
        Claim(id=1, manuscript_text=_SENTENCE, extracted_claim=_SENTENCE, reference_ids=[1],
              cited_for="Gels lower IL-6", co_cited_count=2),
        Claim(id=2, manuscript_text="Combining these.", extracted_claim="Combining these.",
              reference_ids=[3], cited_for="Combining these.", claim_quality="fragment",
              mapping_ambiguous=True, candidate_reference_ids=[1, 2]),
    ]
    verifications = [
        VerificationResult(
            claim_id=1, reference_id=1, verdict="partially_supported", confidence=0.6,
            consensus_type="disputed", needs_user_review=True, decided_by="verifier",
            layer_path=["verifier", "confirm"],
            model_reasoning=[
                ModelReasoning(model_name="claude-haiku-5-5", verdict="not_supported",
                               reasoning="No IL-6 data."),
                ModelReasoning(model_name="gpt-6-luna", verdict="supported",
                               reasoning="IL-6 fell (P2).")]),
        VerificationResult(claim_id=2, reference_id=3, cannot_verify_reason="reference_mismatch",
                           reasoning="The attached PDF does not match this reference"),
    ]
    return refs, claims, verifications


@pytest.fixture
def client() -> Iterator[TestClient]:
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    refs, claims, verifications = _rows()
    with Session(engine) as db:
        db.add_all([reference_to_db(r, "s") for r in refs])
        db.add_all([claim_to_db(c, "s") for c in claims])
        db.add_all([verification_to_db(v, "s") for v in verifications])
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


class TestResults:
    def test_claim_detail_and_signals(self, client: TestClient) -> None:
        items = client.get("/api/sessions/s/results?sort=ref_id").json()["results"]
        first, second = items
        assert first["claim"]["cited_for"] == "Gels lower IL-6"
        dispute = first["signals"]["dispute"]
        assert dispute["verifier"]["verdict"] == "not_supported"
        assert dispute["cross_check"] == {"verdict": "supported", "model_name": "gpt-6-luna",
                                          "explanation": "IL-6 fell (P2)."}
        assert dispute["shown_verdict"] == "partially_supported"
        assert second["claim"]["cited_for"] == ""  # covers the whole sentence
        assert second["claim"]["claim_quality"] == "fragment"
        assert second["claim"]["mapping_ambiguous"] is True
        assert "could refer to [1] or [2]" in second["claim"]["mapping_note"]
        assert second["signals"]["source_problem"] == "reference_mismatch"

    def test_evidence_endpoint_carries_signals(self, client: TestClient) -> None:
        data = client.get("/api/sessions/s/evidence/1").json()
        assert data["claim"]["signals"]["cited_for"] == "Gels lower IL-6"
        assert data["verifications"][0]["signals"]["dispute"]["cross_check"]["verdict"] \
            == "supported"


class TestSourceIssues:
    def test_endpoint_lists_issues_with_labels(self, client: TestClient) -> None:
        data = client.get("/api/sessions/s/source-issues").json()
        kinds = [i["kind"] for i in data["issues"]]
        assert kinds == ["wrong_pdf", "duplicate", "ambiguous_citation"]
        assert data["issues"][0]["claim_ids"] == [2]
        assert data["labels"]["duplicate"] == "Duplicate reference"

    def test_report_preview_has_issues_and_cited_for(self, client: TestClient) -> None:
        preview = client.get("/api/sessions/s/report/preview").json()
        assert [i["kind"] for i in preview["source_issues"]] == [
            "wrong_pdf", "duplicate", "ambiguous_citation"]
        minor = preview["minor_issues"][0]
        assert minor["cited_for"] == "Gels lower IL-6" and minor["disputed"] == "yes"


def test_editing_a_claim_resets_its_cited_for(client: TestClient) -> None:
    r = client.put("/api/sessions/s/claims/1", json={"extracted_claim": "Gels lower IL-6 a lot."})
    assert r.status_code == 200 and r.json()["cited_for"] == "Gels lower IL-6 a lot."
    claim = client.get("/api/sessions/s/results").json()["results"][0]["claim"]
    assert claim["cited_for"] == ""  # the edited text is now judged as a whole


class TestStageMessages:
    def test_parse_and_detect_summaries_name_the_problems(self) -> None:
        refs, claims, _ = _rows()
        assert parse_summary(ParsedManuscript(filename="m", references=refs)) == \
            "3 references extracted (1 duplicate entry)"
        assert detect_summary(5, claims) == \
            "5 citations, 2 claims (1 ambiguous citation mapping, 1 incomplete sentence)"
        assert detect_summary(5, claims * 2) == \
            "5 citations, 4 claims (2 ambiguous citation mappings, 2 incomplete sentences)"
        assert detect_summary(1, []) == "1 citations, 0 claims"

    def test_resolve_summary_counts_repaired_titles(self) -> None:
        refs = [Reference(id=1, source_status="found", repair_applied="title_from_api")]
        assert resolve_summary(refs) == "1 found, 1 with title from DOI/PMID record"
