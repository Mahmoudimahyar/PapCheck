"""Signals the report and UI show next to a verdict, pinned to the verify stage's output.

Regression for the V4.9 review: 36/40 "not supported" flags were disputes between
the verifier and the cross-check, a wrong / scanned / supplement PDF was used
as the article, a supporting passage was itself a secondary citation and claim
figures appeared nowhere in the source, yet the report and the UI showed only
a verdict and one block of reasoning text. The verify stage records these as
notes in ``reasoning``; these tests build results with the REAL verify-stage
code (mocked LLM layers) so a wording change there breaks the parser here.
"""

import time
from unittest.mock import patch

import pytest

from refcheck.models.cannot_verify import PDF_PROBLEM_REASONS
from refcheck.models.verification import ModelReasoning, VerificationResult
from refcheck.stages.generate_report.result_signals import (
    dispute_views,
    numbers_not_found,
    result_signals,
    source_problem,
)
from refcheck.stages.verify_claims import source_fallback
from refcheck.stages.verify_claims.calibration import ScreenThresholds
from refcheck.stages.verify_claims.cascade import CascadeOutcome, run_cascade
from refcheck.stages.verify_claims.cascade_helpers import build_result
from refcheck.stages.verify_claims.layers import LayerResult, ValidatedQuote
from refcheck.stages.verify_claims.source_document import build_abstract_document
from tests.unit.verify_fakes import ABSTRACT, layer, make_claim, make_ctx

_ON = ScreenThresholds()
_CITING = "Older patients had a higher risk of graft failure in long-term studies [10, 11, 23]."


def _outcome(label: LayerResult) -> CascadeOutcome:
    return CascadeOutcome(verdict=label.verdict or "", label_layer=label, decided_by="verifier",
                          consensus_type="verifier", tier=2, layers=[label],
                          layer_path=["verifier"])


async def _disputed(verifier: str, confirm: str) -> VerificationResult:
    script = {
        "verifier": [layer("verifier", verifier, role_quote="closest", provider="anthropic",
                           model_id="claude-haiku-5-5", missing="No figure for Y.")],
        "confirm": [layer("confirm", confirm, provider="openai", model_id="gpt-6-luna")],
    }

    async def fake_run_layer(role: str, pack: object, claim: object, ctx: object,
                             template: str, **kwargs: object) -> LayerResult:
        return script[str(kwargs["layer"])].pop(0)

    ctx = make_ctx()
    with patch("refcheck.stages.verify_claims.cascade.run_layer", fake_run_layer):
        out = await run_cascade(ctx, None, _ON, deadline=time.monotonic() + 100)
    return build_result(ctx, None, out, _ON, 1)


class TestDispute:
    async def test_both_views_of_a_real_disputed_result(self) -> None:
        result = await _disputed("not_supported", "partially_supported")
        assert result.consensus_type == "disputed"
        views = dispute_views(result)
        assert views is not None
        assert (views.verifier.verdict, views.cross_check.verdict, views.shown_verdict) == (
            "not_supported", "partially_supported", "partially_supported")
        assert views.verifier.model_name == "claude-haiku-5-5"
        assert views.cross_check.model_name == "gpt-6-luna"
        assert "No figure for Y." in views.verifier.explanation
        assert views.cross_check.explanation

    async def test_override_keeps_the_cascade_verdict_as_shown(self) -> None:
        result = await _disputed("not_supported", "supported")
        overridden = result.model_copy(update={
            "verdict": "supported", "user_override": True,
            "original_verdict": result.verdict})
        views = dispute_views(overridden)
        assert views is not None and views.shown_verdict == "partially_supported"

    def test_confirmed_and_legacy_results(self) -> None:
        confirmed = VerificationResult(claim_id=1, reference_id=1, consensus_type="confirmed")
        assert dispute_views(confirmed) is None
        legacy = VerificationResult(  # no layer_path: layers from the display prefix
            claim_id=1, reference_id=1, verdict="not_supported", consensus_type="disputed",
            model_reasoning=[
                ModelReasoning(model_name="m1", model_display="Verifier · m1",
                               verdict="not_supported", reasoning="absent"),
                ModelReasoning(model_name="m2", model_display="Confirm · m2",
                               verdict="supported", reasoning="stated in P3")])
        views = dispute_views(legacy)
        assert views is not None and views.cross_check.explanation == "stated in P3"


class TestNotes:
    def test_secondary_citation_note(self) -> None:
        supported = layer("verifier", "supported")
        supported.validated_quotes[0] = ValidatedQuote(
            passage_id="P1", text=_CITING, role="supports", similarity=1.0, source_span=_CITING)
        # a point the paper does not state itself (V5.6 own-statement check)
        ctx = make_ctx(make_claim("Older patients had a higher risk of graft failure."))
        result = build_result(ctx, None, _outcome(supported), _ON, 1)
        signals = result_signals(result)
        assert signals.secondary_citation and not signals.numbers_not_found

    @pytest.mark.parametrize(("claim", "coverage", "co_cited", "expected"), [
        ("Gels reach compressive moduli of up to 150 kPa in mice.", "full_text", 1,
         ["150 kPa"]),
        ("Gels reach 150 kPa and 1.8–120 kPa in mice.", "full_text", 3,
         ["150 kPa", "1.8 kPa", "120 kPa"]),
        ("Drug X cut inflammation by 65% in mice.", "abstract_only", 1, ["65%"]),
    ])
    def test_numbers_not_found_note(self, claim: str, coverage: str, co_cited: int,
                                    expected: list[str]) -> None:
        ctx = make_ctx(make_claim(claim, co_cited=co_cited), coverage=coverage)
        result = build_result(ctx, None, _outcome(layer("verifier", "partially_supported")),
                              _ON, 1)
        # the qualifier "(only the abstract ...)" / "(the sentence cites ...)" is not a number
        assert numbers_not_found(result.reasoning) == expected
        assert result_signals(result).numbers_not_found == expected

    def test_ordinary_result_has_no_signals(self) -> None:
        result = build_result(make_ctx(), None, _outcome(layer("verifier", "supported")), _ON, 1)
        signals = result_signals(result)
        assert signals.dispute is None and not signals.secondary_citation
        assert signals.numbers_not_found == [] and signals.source_problem is None


class TestSourceProblem:
    @pytest.mark.parametrize("quality_reason", sorted(source_fallback._NOTES))
    def test_every_abstract_fallback_note_is_recognised(self, quality_reason: str) -> None:
        doc = build_abstract_document(1, ABSTRACT, quality_reason)
        positive = VerificationResult(claim_id=1, reference_id=1, verdict="supported",
                                      reasoning="The abstract states it.")
        annotated = source_fallback.annotate_source_fallback(positive, doc)
        assert annotated.verdict == "supported"  # the note is the only trace
        assert source_problem(annotated) == str(PDF_PROBLEM_REASONS[quality_reason])
        assert result_signals(annotated).source_problem_text

    @pytest.mark.parametrize("reason", ["reference_mismatch", "pdf_scanned", "pdf_supplement",
                                        "pdf_metadata_only"])
    def test_cannot_verify_reason(self, reason: str) -> None:
        cv = VerificationResult(claim_id=1, reference_id=1, cannot_verify_reason=reason)
        assert source_problem(cv) == reason

    def test_other_reasons_are_not_pdf_problems(self) -> None:
        for reason in ("abstract_insufficient", "llm_error", "no_pdf_paywalled", None):
            cv = VerificationResult(claim_id=1, reference_id=1, cannot_verify_reason=reason)
            assert source_problem(cv) is None
