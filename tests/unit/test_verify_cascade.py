"""V5.1 routing: screen clear, verifier finals, expanded re-run, cross-family check, judge."""

import time
from unittest.mock import patch

import pytest

from refcheck.stages.verify_claims.calibration import ScreenThresholds
from refcheck.stages.verify_claims.cascade import CascadeOutcome, run_cascade
from refcheck.stages.verify_claims.layers import LayerResult
from refcheck.stages.verify_claims.screen import ScreenResult
from refcheck.stages.verify_claims.verifier_helpers import PairContext
from tests.unit.verify_fakes import layer, make_claim, make_ctx, screen

_ON = ScreenThresholds()


def sonnet(verdict: str = "supported", role_quote: str = "supports") -> LayerResult:
    return layer("judge", verdict, role_quote=role_quote, provider="anthropic",
                 model_id="claude-sonnet-5-5")


def sol(verdict: str = "supported") -> LayerResult:
    return layer("confirm", verdict, provider="openai", model_id="gpt-6.1-sol")


async def _route(script: dict[str, list[LayerResult]], ctx: PairContext | None = None,
                 scr: ScreenResult | None = None) -> tuple[CascadeOutcome, list[str]]:
    calls: list[str] = []

    async def fake_run_layer(role: str, pack: object, claim: object, ctx: object,
                             template: str, **kwargs: object) -> LayerResult:
        name = str(kwargs["layer"])
        calls.append(name)
        assert (template == "judge_claim") == (role == "judge")
        return script[name].pop(0)

    with patch("refcheck.stages.verify_claims.cascade.run_layer", fake_run_layer):
        out = await run_cascade(ctx or make_ctx(), scr, _ON, deadline=time.monotonic() + 100)
    return out, calls


async def test_screen_clear_with_verifier_cosign() -> None:
    out, calls = await _route({"verifier": [layer("verifier")]}, scr=screen(0.99))
    assert calls == ["verifier"]
    assert (out.verdict, out.decided_by, out.consensus_type, out.tier) == \
        ("supported", "screen", "screen_clear", 1)
    assert out.layer_path == ["screen", "verifier"]


async def test_verifier_final_when_screen_not_clear() -> None:
    ctx = make_ctx(make_claim("Drug X reduced inflammation by 40% in mice."))
    out, calls = await _route({"verifier": [layer("verifier", "partially_supported",
                                                   severity="minor")]}, ctx, screen(0.99))
    assert calls == ["verifier"] and out.decided_by == "verifier" and out.tier == 2
    assert out.verdict == "partially_supported" and "numeric_claim" in out.failed_gates


async def test_unquoted_positive_is_cross_checked_and_reviewed() -> None:
    out, calls = await _route({"verifier": [layer("verifier", supports=False)],
                               "confirm": [layer("confirm", "supported", provider="anthropic",
                                                 model_id="claude-sonnet-5-5")]},
                              scr=screen(0.99))
    assert calls == ["verifier", "confirm"] and out.decided_by == "verifier"
    assert out.consensus_type == "confirmed" and out.needs_review
    # the cross-check had the validated quote, so its explanation is shown
    assert out.label_layer is not None and out.label_layer.layer == "confirm"


def haiku(verdict: str = "not_supported", role_quote: str = "closest") -> LayerResult:
    return layer("verifier", verdict, role_quote=role_quote, provider="anthropic",
                 model_id="claude-haiku-5-5")


def luna_confirm(verdict: str = "not_supported") -> LayerResult:
    return layer("confirm", verdict, role_quote="closest", provider="openai",
                 model_id="gpt-6-luna")


async def test_major_severity_partial_is_final_at_verifier() -> None:
    out, calls = await _route({"verifier": [layer("verifier", "partially_supported",
                                                   severity="major")]})
    assert calls == ["verifier"]
    assert (out.verdict, out.decided_by, out.consensus_type) == (
        "partially_supported", "verifier", "verifier")


async def test_screen_conflict_positive_shows_cross_check_problem() -> None:
    out, calls = await _route({"verifier": [layer("verifier")],
                               "confirm": [luna_confirm("not_supported")]},
                              ctx=make_ctx(), scr=screen(0.4, conflicts=0.8))
    assert calls == ["verifier", "confirm"]
    assert (out.verdict, out.decided_by, out.consensus_type) == (
        "partially_supported", "verifier", "disputed")
    assert out.needs_review and out.label_layer is not None
    assert out.label_layer.layer == "confirm"


async def test_partial_with_screen_conflict_keeps_partial_when_disputed() -> None:
    out, calls = await _route({"verifier": [layer("verifier", "partially_supported")],
                               "confirm": [luna_confirm("not_supported")]},
                              scr=screen(0.4, conflicts=0.8))
    assert calls == ["verifier", "confirm"]
    assert (out.verdict, out.consensus_type) == ("partially_supported", "disputed")
    assert out.needs_review and out.label_layer is not None
    assert out.label_layer.layer == "verifier"


async def test_judge_for_unusual_positives_is_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFCHECK_JUDGE_UNUSUAL_POSITIVES", "1")
    out, calls = await _route({"verifier": [layer("verifier")],
                               "judge": [sonnet("partially_supported")]},
                              scr=screen(0.4, conflicts=0.8))
    assert calls == ["verifier", "judge"]
    assert (out.verdict, out.decided_by, out.consensus_type) == (
        "partially_supported", "judge", "judge")


async def test_insufficient_reruns_verifier_on_expanded_pack_once() -> None:
    out, calls = await _route({"verifier": [layer("verifier", "insufficient_evidence")],
                               "verifier_expanded": [layer("verifier_expanded")]})
    assert calls == ["verifier", "verifier_expanded"]
    assert out.decided_by == "verifier" and out.label_layer is not None
    assert out.label_layer.pack_kind == "expanded"


async def test_abstract_only_insufficient_needs_no_judge() -> None:
    ctx = make_ctx(coverage="abstract_only")
    out, calls = await _route({"verifier": [layer("verifier", "insufficient_evidence")]}, ctx)
    assert calls == ["verifier"]
    assert out.verdict == "cannot_verify" and out.cv_reason == "abstract_insufficient"


async def test_still_insufficient_after_expanded_is_insufficient_in_source() -> None:
    out, calls = await _route({"verifier": [layer("verifier", "insufficient_evidence")],
                               "verifier_expanded": [layer("verifier_expanded",
                                                           "insufficient_evidence")]})
    assert calls == ["verifier", "verifier_expanded"]
    assert out.verdict == "cannot_verify" and out.cv_reason == "insufficient_in_source"
