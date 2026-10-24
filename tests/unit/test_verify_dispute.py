"""M1: a negative verdict disputed by the blind cross-check is not shown as the harsher label.

Regression for the V4.9 manuscript review: 36/40 "not supported" flags were
disputes (verifier not_supported, cross-check partially_supported / supported)
and the old rule kept the verifier's verdict; the manual review sided with the
cross-check in most of them.
"""

import time
from itertools import product
from unittest.mock import patch

import pytest

from refcheck.stages.verify_claims.calibration import ScreenThresholds
from refcheck.stages.verify_claims.cascade import CascadeOutcome, run_cascade
from refcheck.stages.verify_claims.cascade_helpers import build_result
from refcheck.stages.verify_claims.dispute import disputed_verdict, is_credit_line
from refcheck.stages.verify_claims.layers import LayerResult
from tests.unit.verify_fakes import RESULT_TEXT, layer, make_claim, make_ctx

_ON = ScreenThresholds()
_LAYER_VERDICTS = ("supported", "partially_supported", "not_supported", "contradicted",
                   "not_relevant", "insufficient_evidence", None)


@pytest.mark.parametrize(("verifier", "confirm", "shown"), [
    ("not_supported", "partially_supported", "partially_supported"),
    ("not_supported", "supported", "partially_supported"),  # never plain "supported"
    ("not_relevant", "partially_supported", "not_supported"),
    ("not_relevant", "supported", "not_supported"),
    ("contradicted", "supported", "contradicted"),  # categorical finding: kept
    ("not_supported", "insufficient_evidence", "not_supported"),  # cross-check undecided
    ("not_supported", None, "not_supported"),
])
def test_disputed_verdict_table(verifier: str, confirm: str | None, shown: str) -> None:
    assert disputed_verdict(verifier, confirm) == shown


def test_dispute_never_shows_supported_or_a_harsher_label() -> None:
    severity = {"supported": 0, "partially_supported": 1, "not_supported": 2,
                "not_relevant": 3, "contradicted": 3}
    for verifier, confirm in product(("not_supported", "contradicted", "not_relevant"),
                                     _LAYER_VERDICTS):
        shown = disputed_verdict(verifier, confirm)
        assert shown != "supported"
        assert severity[shown] <= severity[verifier]


def haiku(verdict: str, missing: str | None = "The source lacks the claimed finding.",
          ) -> LayerResult:
    return layer("verifier", verdict, role_quote="closest", provider="anthropic",
                 model_id="claude-haiku-5-5", missing=missing)


def luna(verdict: str, role_quote: str = "supports") -> LayerResult:
    return layer("confirm", verdict, role_quote=role_quote, provider="openai",
                 model_id="gpt-6-luna")


async def _route(verifier: LayerResult, confirm: LayerResult) -> CascadeOutcome:
    script = {"verifier": [verifier], "confirm": [confirm]}

    async def fake_run_layer(role: str, pack: object, claim: object, ctx: object,
                             template: str, **kwargs: object) -> LayerResult:
        return script[str(kwargs["layer"])].pop(0)

    with patch("refcheck.stages.verify_claims.cascade.run_layer", fake_run_layer):
        return await run_cascade(make_ctx(), None, _ON, deadline=time.monotonic() + 100)


async def test_not_supported_disputed_by_partial_is_shown_as_partial() -> None:
    out = await _route(haiku("not_supported"), luna("partially_supported"))
    assert (out.verdict, out.consensus_type, out.decided_by) == (
        "partially_supported", "disputed", "verifier")
    assert out.needs_review
    # the cross-check's explanation and supports quote back the shown positive verdict
    assert out.label_layer is not None and out.label_layer.layer == "confirm"
    note = " ".join(out.notes)
    assert "the verifier said not_supported" in note and "shown as partially_supported" in note
    assert "Verifier: The source lacks the claimed finding." in note
    assert "Cross-check: Explanation for partially_supported" in note


async def test_not_relevant_disputed_steps_down_to_not_supported() -> None:
    out = await _route(haiku("not_relevant"), luna("partially_supported"))
    assert (out.verdict, out.consensus_type) == ("not_supported", "disputed")
    assert out.needs_review and out.label_layer is not None
    assert out.label_layer.layer == "verifier"


async def test_undecided_cross_check_keeps_the_verifier_verdict() -> None:
    out = await _route(haiku("not_supported"), luna("insufficient_evidence", "closest"))
    assert (out.verdict, out.consensus_type) == ("not_supported", "disputed")
    assert out.needs_review and "shown as" not in " ".join(out.notes)


async def test_agreement_is_unchanged() -> None:
    out = await _route(haiku("not_supported"), luna("not_supported", "closest"))
    assert (out.verdict, out.consensus_type) == ("not_supported", "confirmed")
    assert not out.needs_review


async def test_final_result_of_a_dispute_records_both_views() -> None:
    ctx = make_ctx()
    out = await _route(haiku("not_supported", missing="No passage reports it."),
                       luna("supported"))
    result = build_result(ctx, None, out, _ON, latency_ms=10)
    assert result.verdict == "partially_supported"
    assert result.consensus_type == "disputed" and result.needs_user_review
    assert result.confidence <= 0.70
    assert "Verifier: No passage reports it." in result.reasoning
    assert RESULT_TEXT in result.evidence_quotes
    assert [v.verdict for v in result.votes] == ["not_supported", "supported"]


async def test_secondary_citation_in_the_cross_check_quote_is_surfaced() -> None:
    """V4.9 case-5 shape: the passage that supports the claim cites other studies."""
    confirm = luna("partially_supported")
    confirm.validated_quotes[0] = confirm.validated_quotes[0].model_copy(update={
        "text": "Risk rose in older patients in long-term studies [10, 11, 23]."})
    out = await _route(haiku("not_supported"), confirm)
    # a point the paper does not state itself (V5.6 own-statement check)
    ctx = make_ctx(make_claim("Older patients had a higher risk of graft failure."))
    result = build_result(ctx, None, out, _ON, latency_ms=10)
    assert result.verdict == "partially_supported"
    assert "Secondary citation" in result.reasoning


def test_strict_policy_keeps_the_verifier_verdict(monkeypatch: "pytest.MonkeyPatch") -> None:
    from refcheck.stages.verify_claims.dispute import disputed_verdict

    monkeypatch.setenv("REFCHECK_DISPUTE_POLICY", "strict")
    assert disputed_verdict("not_supported", "supported") == "not_supported"
    monkeypatch.setenv("REFCHECK_DISPUTE_POLICY", "soften")
    assert disputed_verdict("not_supported", "supported") == "partially_supported"
    monkeypatch.setenv("REFCHECK_DISPUTE_POLICY", "bogus")
    assert disputed_verdict("not_supported", "supported") == "partially_supported"


@pytest.mark.parametrize(("text", "credit"), [
    ("Adapted from Roe et al.", True),
    ("Reproduced with permission from Roe et al. (2019).", True),
    ("(a) Reprinted from ref. 12", True),
    ("Modified from", True),
    ("Adapted from Paul et al. (2022), Copyright 2022 Elsevier.", True),
    ("Cells adapted from the donor were cultured", False),
    ("Taken together, these data from multiple cohorts indicate that", False),
    ("Taken together, results from these studies suggest", False),
    ("Adapted from the protocol of Smith et al., cells were cultured in DMEM.", False),
    ("Adapted from previously published methods [12], islets were isolated", False),
    ("Modified alginate hydrogels from brown algae reduce fibrosis.", False),
    ("Adapted from the protocol of Smith et al. cells were cultured in warm DMEM", False),
    ("Data taken in triplicate were averaged from three runs", False),
    ("Hydrogels reduce fibrosis", False),
    ("", False),
])
def test_credit_line_detection(text: str, credit: bool) -> None:
    assert is_credit_line(text) is credit


@pytest.mark.parametrize(("verifier", "confirm", "shown"), [
    ("not_relevant", "supported", "supported"),
    ("not_supported", "partially_supported", "partially_supported"),
    ("not_relevant", "insufficient_evidence", "not_relevant"),  # undecided: kept
    ("not_relevant", "not_supported", "not_relevant"),  # both negative: kept
])
def test_credit_line_dispute_shows_the_cross_check(verifier: str, confirm: str,
                                                   shown: str) -> None:
    assert disputed_verdict(verifier, confirm, credit=True) == shown


def test_strict_policy_also_keeps_credit_line_verdicts(monkeypatch: "pytest.MonkeyPatch") -> None:
    monkeypatch.setenv("REFCHECK_DISPUTE_POLICY", "strict")
    assert disputed_verdict("not_relevant", "supported", credit=True) == "not_relevant"
