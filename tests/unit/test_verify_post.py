"""POST rules and result mapping (build_result) for the V5 cascade."""

from refcheck.stages.verify_claims.calibration import ScreenThresholds
from refcheck.stages.verify_claims.cascade import CascadeOutcome
from refcheck.stages.verify_claims.cascade_helpers import build_result
from refcheck.stages.verify_claims.layers import LayerResult, ValidatedQuote
from tests.unit.verify_fakes import RESULT_TEXT, layer, make_claim, make_ctx, screen

_ON = ScreenThresholds()


def _outcome(label: LayerResult, verdict: str | None = None, **extra: object) -> CascadeOutcome:
    fields: dict[str, object] = {
        "verdict": verdict or label.verdict or "cannot_verify", "label_layer": label,
        "decided_by": "judge", "consensus_type": "judge", "tier": 3, "layers": [label],
        "layer_path": ["screen", label.layer],
    }
    fields.update(extra)
    return CascadeOutcome.model_validate(fields)


def test_supported_result_fields_and_trace() -> None:
    ctx = make_ctx()
    l2 = layer("verifier", cost=0.0006)
    judge = layer("judge", provider="anthropic", model_id="claude-sonnet-5-5", cost=0.01)
    out = _outcome(judge, layers=[l2, judge], layer_path=["screen", "verifier", "judge"])
    result = build_result(ctx, screen(0.9), out, _ON, latency_ms=4200)
    assert result.verdict == "supported" and result.decided_by == "judge"
    assert result.tier == result.final_tier == 3 and result.escalation_path == [1, 2, 3]
    assert result.evidence_quotes == [RESULT_TEXT] and result.quotes_validated is True
    assert result.cost_usd == round(0.0005 + 0.0006 + 0.01, 6) and result.latency_ms == 4200
    assert result.screen_p_support == 0.9 and result.screen_p_topic == 1.0
    assert result.screen_p_contradict == 0.0 and result.source_coverage == "full_text"
    displays = [m.model_display for m in result.model_reasoning]
    assert displays == ["Decisions API · gpt-6-luna", "Verifier · gpt-6-luna",
                        "Judge · claude-sonnet-5-5"]
    assert [v.abbreviation for v in result.votes] == ["S", "V", "J"]
    assert result.agreement_ratio == 1.0 and not result.needs_user_review
    assert result.evidence_sections and result.evidence_sections[0].page_number == 4


def test_abstract_only_not_supported_becomes_cannot_verify() -> None:
    ctx = make_ctx(coverage="abstract_only")
    result = build_result(ctx, None, _outcome(layer("judge", "not_supported",
                                                    role_quote="closest")), _ON, 10)
    assert result.verdict == "cannot_verify"
    assert result.cannot_verify_reason == "abstract_insufficient"
    assert result.source_coverage == "abstract_only"


def test_abstract_only_kept_with_validated_contradicts_quote() -> None:
    ctx = make_ctx(coverage="abstract_only")
    result = build_result(ctx, None, _outcome(layer("judge", "not_supported",
                                                    role_quote="contradicts")), _ON, 10)
    assert result.verdict == "not_supported" and result.confidence <= 0.6


def test_contradicted_always_needs_review() -> None:
    result = build_result(make_ctx(), None, _outcome(layer("judge", "contradicted",
                                                           role_quote="contradicts")), _ON, 1)
    assert result.verdict == "contradicted" and result.needs_user_review


def test_negative_without_quote_or_missing_needs_review() -> None:
    bare = layer("judge", "not_supported", supports=False)
    assert build_result(make_ctx(), None, _outcome(bare), _ON, 1).needs_user_review
    noted = layer("judge", "not_supported", supports=False, missing="No outcome data.")
    result = build_result(make_ctx(), None, _outcome(noted), _ON, 1)
    assert not result.needs_user_review and "Missing: No outcome data." in result.reasoning


def test_numeric_mismatch_adds_note_without_changing_verdict() -> None:
    ctx = make_ctx(make_claim("Drug X reduced IL-6 levels by 70% in mice."))
    result = build_result(ctx, None, _outcome(layer("judge", "supported")), _ON, 1)
    assert result.verdict == "supported" and result.needs_user_review
    assert "70%" in result.reasoning and "40%" in result.reasoning


def _negative_with_confirm(confirm_verdict: str, consensus: str, review: bool,
                           confirm_provider: str = "openai") -> CascadeOutcome:
    l2 = layer("verifier", "not_supported", role_quote="closest", provider="anthropic",
               model_id="claude-haiku-5-5")
    confirm = layer("confirm", confirm_verdict, role_quote="closest", provider=confirm_provider)
    return _outcome(l2, decided_by="verifier", consensus_type=consensus, tier=2,
                    layers=[l2, confirm], layer_path=["screen", "verifier", "confirm"],
                    needs_review=review, notes=[f"Cross-check: {consensus}."])


def test_disputed_negative_caps_confidence_and_needs_review() -> None:
    out = _negative_with_confirm("supported", "disputed", review=True)
    result = build_result(make_ctx(), None, out, _ON, 1)
    assert result.verdict == "not_supported" and result.decided_by == "verifier"
    assert result.consensus_type == "disputed" and result.tier == 2
    assert result.needs_user_review and result.confidence == 0.7
    assert result.agreement_ratio == 0.5
    assert result.reasoning.endswith("Cross-check: disputed.")


def test_unconfirmed_negative_caps_confidence() -> None:
    l2 = layer("verifier", "not_supported", role_quote="closest")
    failed = layer("confirm", error="transient: down")
    out = _outcome(l2, decided_by="verifier", consensus_type="verifier_unconfirmed", tier=2,
                   layers=[l2, failed], layer_path=["screen", "verifier", "confirm"],
                   needs_review=True, notes=["The cross-check call failed."])
    result = build_result(make_ctx(), None, out, _ON, 1)
    assert result.verdict == "not_supported" and result.needs_user_review
    assert result.confidence == 0.7
    assert result.reasoning.endswith("The cross-check call failed.")


def test_confirmed_negative_keeps_confidence() -> None:
    result = build_result(make_ctx(), None,
                          _negative_with_confirm("not_supported", "confirmed", review=False),
                          _ON, 1)
    assert result.consensus_type == "confirmed" and not result.needs_user_review
    assert result.confidence == 0.9 and result.agreement_ratio == 1.0
    # Same-family confirmation is flagged for review but is not a disagreement.
    same = _negative_with_confirm("not_supported", "confirmed", review=True,
                                  confirm_provider="anthropic")
    result = build_result(make_ctx(), None, same, _ON, 1)
    assert result.needs_user_review and result.confidence == 0.9


def test_contrast_claim_review_only_when_negative_or_low_confidence() -> None:
    ctx = make_ctx(make_claim(claim_type="contrast"))
    ok = build_result(ctx, None, _outcome(layer("judge", "supported")), _ON, 1)
    assert not ok.needs_user_review
    neg = build_result(ctx, None, _outcome(layer("judge", "not_relevant",
                                                 role_quote="closest")), _ON, 1)
    assert neg.needs_user_review


def test_llm_error_outcome_keeps_coverage() -> None:
    failed = layer("verifier", error="transient: down")
    out = CascadeOutcome(verdict="cannot_verify", cv_reason="llm_error", tier=2,
                         error="verifier: transient: down", layers=[failed],
                         layer_path=["verifier"])
    result = build_result(make_ctx(), None, out, _ON, 1)
    assert result.verdict == "cannot_verify" and result.cannot_verify_reason == "llm_error"
    assert result.source_coverage == "full_text" and "LLM/API error" in result.reasoning
    assert result.model_reasoning[0].verdict == "error"


def test_invalid_quotes_mark_quotes_validated_false() -> None:
    judge = layer("judge", "supported")
    judge = judge.model_copy(update={
        "invalid_quotes": ["made up"],
        "validated_quotes": [ValidatedQuote(passage_id="P1", text=RESULT_TEXT, role="supports")],
    })
    assert build_result(make_ctx(), None, _outcome(judge), _ON, 1).quotes_validated is False
