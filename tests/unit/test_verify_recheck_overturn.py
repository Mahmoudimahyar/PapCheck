"""Evidence re-check that overturns a negative verdict: cross-checked, reviewed, quote kept."""

import time
from unittest.mock import patch

import pytest

from refcheck.stages.verify_claims.calibration import ScreenThresholds
from refcheck.stages.verify_claims.cascade import CascadeOutcome, run_cascade
from refcheck.stages.verify_claims.layers import LayerResult, ValidatedQuote
from refcheck.stages.verify_claims.recheck import overturn_note, overturned
from refcheck.stages.verify_claims.retriever import EvidencePack
from refcheck.stages.verify_claims.screen import ScreenResult
from refcheck.stages.verify_claims.verifier_helpers import PairContext
from tests.unit.verify_fakes import layer, make_ctx, screen

_ON = ScreenThresholds()
_ELEMENT = "body weight did not differ between the groups"
_CONTRA = "Drug X increased inflammation markers in treated mice."


def _with(lay: LayerResult, *elements: str, contra: bool = False) -> LayerResult:
    assert lay.output is not None
    out = lay.output.model_copy(update={"unsupported_elements": list(elements)})
    quotes = list(lay.validated_quotes)
    if contra:
        quotes.append(ValidatedQuote(passage_id="A", text=_CONTRA, role="contradicts"))
    return lay.model_copy(update={"output": out, "validated_quotes": quotes})


def _ctx() -> PairContext:
    ctx = make_ctx()
    ctx.use_embeddings = False  # BM25 only: no embedding call in unit tests
    return ctx


async def _route(script: dict[str, list[LayerResult]],
                 scr: ScreenResult | None = None) -> tuple[list[str], CascadeOutcome]:
    calls: list[str] = []

    async def fake_run_layer(role: str, pack: EvidencePack, claim: object, c: object,
                             template: str, **kwargs: object) -> LayerResult:
        calls.append(str(kwargs["layer"]))
        result = script[str(kwargs["layer"])].pop(0)
        return result.model_copy(update={"pack_kind": kwargs["pack_kind"]})

    with patch("refcheck.stages.verify_claims.cascade.run_layer", fake_run_layer):
        out = await run_cascade(_ctx(), scr, _ON, deadline=time.monotonic() + 100)
    return calls, out


def _contradicted() -> LayerResult:
    return _with(layer("verifier", "contradicted", role_quote="closest"), _ELEMENT, contra=True)


def test_overturned_needs_a_negative_or_contradicting_first_run() -> None:
    supported = layer("verifier_recheck")
    assert overturned(_contradicted(), supported)
    assert overturned(_with(layer("verifier", "not_supported"), _ELEMENT), supported)
    partial = _with(layer("verifier", "partially_supported"), _ELEMENT)
    assert not overturned(partial, supported)  # the ordinary retrieval-miss case
    assert overturned(_with(partial, _ELEMENT, contra=True), supported)
    assert not overturned(_contradicted(), layer("verifier_recheck", "not_supported"))
    assert _CONTRA in overturn_note(_contradicted())


async def test_overturned_contradiction_is_cross_checked_and_reviewed(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFCHECK_V57_DISABLE", "1")  # V5.6 behaviour (no re-check closure)
    calls, out = await _route({
        "verifier": [_contradicted()], "verifier_recheck": [layer("verifier_recheck")],
        "confirm": [layer("confirm", "supported", provider="anthropic",
                          model_id="claude-sonnet-5-5")]}, scr=screen(0.99))
    assert calls == ["verifier", "verifier_recheck", "confirm"]
    assert out.verdict == "supported" and out.needs_review and out.decided_by == "verifier"
    assert out.guards == ["evidence_recheck"]
    assert any(_CONTRA in note for note in out.notes)
    assert any("overturned the first verdict (contradicted)" in note for note in out.notes)


async def test_overturn_confirmed_by_the_cross_check_alone_stays_partial() -> None:
    """V5.7 #1: the first run's elements were never closed (adjudicator off here)."""
    calls, out = await _route({
        "verifier": [_contradicted()], "verifier_recheck": [layer("verifier_recheck")],
        "confirm": [layer("confirm", "supported", provider="anthropic",
                          model_id="claude-sonnet-5-5")]}, scr=screen(0.99))
    assert calls == ["verifier", "verifier_recheck", "confirm"]
    assert out.verdict == "partially_supported" and out.needs_review
    assert out.label_layer is not None and out.label_layer.output is not None
    assert out.label_layer.output.unsupported_elements == [_ELEMENT]
    assert any(_CONTRA in note for note in out.notes)
    assert any("overturned the first verdict (contradicted)" in note for note in out.notes)


async def test_overturn_rejected_by_the_cross_check_shows_the_problem() -> None:
    calls, out = await _route({
        "verifier": [_contradicted()], "verifier_recheck": [layer("verifier_recheck")],
        "confirm": [layer("confirm", "not_supported", role_quote="closest",
                          provider="anthropic", model_id="claude-sonnet-5-5")]})
    assert out.verdict == "not_supported" and out.consensus_type == "disputed"
    assert out.needs_review and out.guards == []


async def test_rechecked_supported_is_never_labelled_screen_clear() -> None:
    first = _with(layer("verifier", "partially_supported", severity="minor"), _ELEMENT)
    calls, out = await _route({"verifier": [first],
                               "verifier_recheck": [layer("verifier_recheck")]},
                              scr=screen(0.99))
    assert calls == ["verifier", "verifier_recheck"] and out.clear_eligible
    assert (out.verdict, out.decided_by, out.tier) == ("supported", "verifier", 2)
