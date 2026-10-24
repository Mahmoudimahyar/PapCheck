"""Small verification helpers: claim-type behaviour, cannot_verify, local context."""

from refcheck.models.cannot_verify import CannotVerifyReason, classify_quality_reason
from refcheck.models.claim import Claim
from refcheck.models.verification import VerificationResult
from refcheck.stages.verify_claims.verifier_helpers import (
    apply_claim_type_behavior,
    cannot_verify,
    dedupe_quotes,
    local_paragraph,
    previous_sentence,
)
from tests.unit.verify_fakes import make_claim, make_ref


def _result(verdict: str, confidence: float = 0.9) -> VerificationResult:
    return VerificationResult(claim_id=1, reference_id=1, verdict=verdict,  # type: ignore[arg-type]
                              confidence=confidence)


def test_background_claims_are_never_upgraded() -> None:
    claim = make_claim(claim_type="background")
    for verdict in ("partially_supported", "cannot_verify"):
        assert apply_claim_type_behavior(_result(verdict), claim).verdict == verdict


def test_contrast_review_only_for_negative_or_low_confidence() -> None:
    claim = make_claim(claim_type="contrast")
    assert not apply_claim_type_behavior(_result("supported"), claim).needs_user_review
    assert apply_claim_type_behavior(_result("supported", 0.4), claim).needs_user_review
    assert apply_claim_type_behavior(_result("not_supported"), claim).needs_user_review
    assert not apply_claim_type_behavior(_result("cannot_verify", 0.0), claim).needs_user_review


def test_cannot_verify_keeps_coverage_and_tier() -> None:
    result = cannot_verify(make_claim(), make_ref(), "LLM failed", "full_text",
                           cv_reason="llm_error", tier=3, text_quality_score=0.8)
    assert result.source_coverage == "full_text" and result.tier == result.final_tier == 3
    assert result.cannot_verify_reason == "llm_error" and result.text_quality_score == 0.8
    default = cannot_verify(make_claim(), make_ref(), "none")
    assert default.source_coverage == "no_source" and default.tier == 1


def test_previous_sentence_and_paragraph_window() -> None:
    first = "The first sentence introduces the general topic of inflammation in mice."
    second = "The second sentence explains why drug X was studied in this model."
    claim = Claim(id=1, manuscript_text="Drug X works [1].",
                  paragraph_text=f"{first} {second} Drug X works [1]. Tail.")
    assert previous_sentence(claim) == second
    assert previous_sentence(Claim(id=2, manuscript_text="x")) == ""
    long_para = "Filler sentence. " * 200 + "Drug X works [1]. " + "More filler. " * 200
    window = local_paragraph(Claim(id=3, manuscript_text="Drug X works [1].",
                                   paragraph_text=long_para))
    assert len(window) <= 1502 and "Drug X works [1]." in window


def test_dedupe_quotes() -> None:
    assert dedupe_quotes(["A  b", "c"], ["a b", "", "d"]) == ["A  b", "c", "d"]


def test_quality_reason_mapping() -> None:
    assert classify_quality_reason("pdf_unreadable", 0.0) == CannotVerifyReason.PDF_SCANNED
    assert classify_quality_reason("likely_supplement", 0.2) == CannotVerifyReason.PDF_SUPPLEMENT
    assert classify_quality_reason("metadata_only", 0.1) == CannotVerifyReason.PDF_METADATA_ONLY
    assert CannotVerifyReason.INSUFFICIENT_IN_SOURCE.value == "insufficient_in_source"
