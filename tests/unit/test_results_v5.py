"""Results API: V5 cascade trace fields, confirmation status and risk sort."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from refcheck.api.main import app
from refcheck.api.routes.results_trace import (
    CONFIRMATION_LABELS,
    confirmation_status,
    layer_names,
    model_family,
    screen_p_problem,
)
from refcheck.db.converters import claim_to_db, verification_to_db
from refcheck.db.deps import get_db
from refcheck.models.claim import Claim
from refcheck.models.verification import ModelReasoning, VerificationResult

_SCREEN = ModelReasoning(model_name="gpt-6-luna-decisions",
                         model_display="Decisions API · gpt-6-luna",
                         verdict="possible_problem", confidence=0.3)


def _layer(prefix: str, model: str, verdict: str) -> ModelReasoning:
    return ModelReasoning(model_name=model, model_display=f"{prefix} · {model}", verdict=verdict)


def _result(claim_id: int, verdict: str, layers: list[tuple[str, ModelReasoning]],
            **extra: object) -> VerificationResult:
    return VerificationResult.model_validate({
        "claim_id": claim_id, "reference_id": claim_id, "verdict": verdict,
        "confidence": 0.8, "layer_path": [name for name, _ in layers],
        "model_reasoning": [entry for _, entry in layers], **extra,
    })


def _confirmed_negative() -> VerificationResult:
    """V5.1: a negative verifier verdict agreed by the blind cross-family check."""
    return _result(1, "not_supported", [
        ("screen", _SCREEN),
        ("verifier", _layer("Verifier", "claude-haiku-5-5", "not_supported")),
        ("confirm", _layer("Confirm", "gpt-6-luna", "contradicted")),
    ], decided_by="verifier", consensus_type="confirmed", screen_p_support=0.3,
        cost_usd=0.012, tier=2, final_tier=2)


def _disputed() -> VerificationResult:
    """V5.1: the cross-check disagreed; the verifier's verdict is kept for review."""
    return _result(2, "not_supported", [
        ("verifier", _layer("Verifier", "claude-haiku-5-5", "not_supported")),
        ("confirm", _layer("Confirm", "gpt-6-luna", "supported")),
    ], decided_by="verifier", consensus_type="disputed", needs_user_review=True,
        screen_p_support=0.9, cost_usd=0.02)


def _screen_clear() -> VerificationResult:
    return _result(3, "supported", [
        ("screen", _SCREEN.model_copy(update={"verdict": "likely_supported"})),
        ("verifier", _layer("Verifier", "gpt-6-luna", "supported")),
    ], decided_by="screen", screen_p_support=0.99, cost_usd=0.0004, tier=1)


class TestTrace:
    def test_layer_names_from_layer_path(self) -> None:
        assert layer_names(_confirmed_negative()) == ["screen", "verifier", "confirm"]

    def test_layer_names_fall_back_to_display_prefix(self) -> None:
        v = _confirmed_negative().model_copy(update={"layer_path": []})
        assert layer_names(v) == ["screen", "verifier", "confirm"]
        expanded = _layer("Verifier (expanded)", "gpt-6-luna", "supported")
        legacy = ModelReasoning(model_name="old-model", model_display="Claude Sonnet")
        v2 = VerificationResult(claim_id=1, reference_id=1, model_reasoning=[expanded, legacy])
        assert layer_names(v2) == ["verifier_expanded", ""]

    def test_confirmed_by_two_families(self) -> None:
        assert confirmation_status(_confirmed_negative()) == "confirmed"

    def test_same_family_agreement(self) -> None:
        # anthropic_only profile: the cross-check is a same-family model
        v = _result(1, "not_supported", [
            ("verifier", _layer("Verifier", "claude-haiku-5-5", "not_supported")),
            ("confirm", _layer("Confirm", "claude-sonnet-5-5", "not_supported")),
        ], decided_by="verifier", consensus_type="confirmed", needs_user_review=True)
        assert confirmation_status(v) == "same_family"
        # an unusual positive judged by a same-family judge
        judged = _result(1, "supported", [
            ("verifier", _layer("Verifier", "claude-haiku-5-5", "supported")),
            ("judge", _layer("Judge", "claude-sonnet-5-5", "partially_supported")),
        ], decided_by="judge", consensus_type="judge")
        assert confirmation_status(judged) == "same_family"

    def test_disputed_and_unconfirmed_come_from_the_consensus(self) -> None:
        assert confirmation_status(_disputed()) == "disputed"
        assert CONFIRMATION_LABELS["disputed"] == "Disputed — needs review"
        failed = _result(5, "not_supported", [
            ("verifier", _layer("Verifier", "claude-haiku-5-5", "not_supported")),
            ("confirm", _layer("Confirm", "gpt-6-luna", "error")),
        ], decided_by="verifier", consensus_type="verifier_unconfirmed", needs_user_review=True)
        assert confirmation_status(failed) == "unconfirmed"
        assert CONFIRMATION_LABELS["unconfirmed"] == "Unconfirmed — needs review"

    def test_legacy_confirm_tiebreak_is_disputed(self) -> None:
        legacy = _result(2, "supported", [
            ("verifier", _layer("Verifier", "gpt-6-luna", "supported")),
            ("judge", _layer("Judge", "claude-sonnet-5-5", "not_supported")),
            ("confirm", _layer("Confirm", "gpt-6.1-sol", "supported")),
        ], decided_by="judge", consensus_type="confirm_majority", needs_user_review=True)
        assert confirmation_status(legacy) == "disputed"

    def test_single_layer_and_cannot_verify_are_none(self) -> None:
        assert confirmation_status(_screen_clear()) == "none"
        cv = _confirmed_negative().model_copy(update={"verdict": "cannot_verify"})
        assert confirmation_status(cv) == "none"
        insufficient = _result(4, "supported", [
            ("verifier", _layer("Verifier", "gpt-6-luna", "insufficient_evidence")),
            ("judge", _layer("Judge", "claude-sonnet-5-5", "supported")),
        ])
        assert confirmation_status(insufficient) == "none"

    def test_model_family_and_p_problem(self) -> None:
        assert model_family("claude-sonnet-5-5") == "anthropic"
        assert model_family("openai/some-new-model") == "openai"
        assert model_family("grok-9") == "xai"
        assert screen_p_problem(_confirmed_negative()) == pytest.approx(0.7)
        assert screen_p_problem(VerificationResult(claim_id=1, reference_id=1)) is None


@pytest.fixture
def client() -> Iterator[TestClient]:
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        for v in (_confirmed_negative(), _disputed(), _screen_clear(),
                  VerificationResult(claim_id=4, reference_id=4)):
            db.add(verification_to_db(v, "s5"))
            db.add(claim_to_db(Claim(id=v.claim_id, extracted_claim=f"claim {v.claim_id}"),
                               "s5"))
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


class TestResultsEndpoint:
    def test_items_expose_cascade_trace(self, client: TestClient) -> None:
        data = client.get("/api/sessions/s5/results?sort=ref_id").json()
        first = data["results"][0]
        assert first["decided_by"] == "verifier" and first["consensus_type"] == "confirmed"
        assert first["screen_p_support"] == pytest.approx(0.3)
        assert first["screen_p_problem"] == pytest.approx(0.7)
        assert first["layer_path"] == ["screen", "verifier", "confirm"]
        assert first["confirmation"] == "confirmed"
        assert first["confirmation_label"] == "Confirmed by 2 model families"
        assert [m["layer"] for m in first["model_reasoning"]] == ["screen", "verifier", "confirm"]
        second = data["results"][1]
        assert second["confirmation"] == "disputed" and second["needs_user_review"]
        assert second["confirmation_label"] == "Disputed — needs review"

    def test_summary_counts_decisions_and_cost(self, client: TestClient) -> None:
        summary = client.get("/api/sessions/s5/results").json()["summary"]
        assert summary["decided_by"] == {"verifier": 2, "screen": 1, "none": 1}
        assert summary["needs_review"] == 1
        assert summary["total_cost_usd"] == pytest.approx(0.0324)

    def test_risk_sort_puts_highest_p_problem_first(self, client: TestClient) -> None:
        results = client.get("/api/sessions/s5/results?sort=risk").json()["results"]
        assert [r["claim_id"] for r in results] == [1, 2, 3, 4]

    def test_override_clears_confirmation(self, client: TestClient) -> None:
        r = client.post("/api/sessions/s5/results/1/override",
                        json={"verdict": "supported", "reason": "checked"})
        assert r.status_code == 200
        assert r.json()["confirmation"] == "none" and r.json()["decided_by"] == "verifier"
