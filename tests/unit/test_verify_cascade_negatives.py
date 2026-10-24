"""V5.1 routing of negative verdicts: the blind cross-family check and its failures."""

import time
from typing import TYPE_CHECKING
from unittest.mock import patch

from refcheck.stages.verify_claims.calibration import ScreenThresholds
from refcheck.stages.verify_claims.cascade import run_cascade
from refcheck.stages.verify_claims.layers import LayerResult
from tests.unit.test_verify_cascade import _route, haiku, luna_confirm
from tests.unit.verify_fakes import layer, make_ctx

if TYPE_CHECKING:
    import pytest

_ON = ScreenThresholds()


async def test_negative_confirmed_by_other_family_is_final() -> None:
    out, calls = await _route({"verifier": [haiku("not_supported")],
                               "confirm": [luna_confirm("not_supported")]})
    assert calls == ["verifier", "confirm"]
    assert (out.verdict, out.decided_by, out.consensus_type) == (
        "not_supported", "verifier", "confirmed")
    assert not out.needs_review and out.tier == 2


async def test_same_family_confirmation_needs_review() -> None:
    out, _ = await _route({"verifier": [haiku("not_supported")],
                           "confirm": [layer("confirm", "not_supported", provider="anthropic",
                                             model_id="claude-sonnet-5-5")]})
    assert out.verdict == "not_supported" and out.consensus_type == "confirmed"
    assert out.needs_review


async def test_disputed_negative_keeps_verifier_verdict_for_review() -> None:
    out, calls = await _route({"verifier": [haiku("contradicted", role_quote="contradicts")],
                               "confirm": [luna_confirm("supported")]})
    assert calls == ["verifier", "confirm"]
    assert (out.verdict, out.consensus_type) == ("contradicted", "disputed")
    assert out.needs_review and any("Disputed" in n for n in out.notes)


async def test_failures() -> None:
    out, _ = await _route({"verifier": [layer("verifier", error="transient: down")]})
    assert out.verdict == "cannot_verify" and out.cv_reason == "llm_error" and out.tier == 2
    # a failed cross-check: the verifier's not_supported is shown one step milder (V5.8 #34)
    out, _ = await _route({"verifier": [haiku("not_supported")],
                           "confirm": [layer("confirm", error="timeout: slow")]})
    assert out.verdict == "partially_supported" and out.consensus_type == "verifier_unconfirmed"
    assert out.needs_review and out.cv_reason is None
    assert any("Shown as partially_supported" in n for n in out.notes)
    # ... but a contradiction is kept
    out, _ = await _route({"verifier": [haiku("contradicted", role_quote="contradicts")],
                           "confirm": [layer("confirm", error="timeout: slow")]})
    assert out.verdict == "contradicted" and out.consensus_type == "verifier_unconfirmed"
    # a failed cross-check on an unusual positive keeps the verifier's verdict for review
    out, _ = await _route({"verifier": [layer("verifier", supports=False)],
                           "confirm": [layer("confirm", error="timeout: slow")]})
    assert out.verdict == "supported" and out.needs_review
    assert out.consensus_type == "verifier_unconfirmed"


async def test_confirm_model_comes_from_another_family() -> None:
    """Verifier is gpt-6-luna (OpenAI): the cross-check must skip OpenAI models."""
    from refcheck.llm.model_registry import REGISTRY

    def fake_resolve(role: str, exclude: tuple[str, ...] | list[str] = ()) -> object:
        order = ["gpt-6-luna", "gpt-6.1-sol", "claude-sonnet-5-5"]
        return next((REGISTRY[m] for m in order if m not in exclude), None)

    def fake_candidates(role: str) -> list[object]:
        return [REGISTRY[m] for m in ["gpt-6-luna", "gpt-6.1-sol", "claude-sonnet-5-5"]]

    models: list[object] = []

    async def fake_run_layer(role: str, pack: object, claim: object, ctx: object,
                             template: str, **kwargs: object) -> LayerResult:
        models.append(kwargs.get("model"))
        script = {"verifier": layer("verifier", "not_supported", role_quote="closest"),
                  "confirm": layer("confirm", "not_supported", provider="anthropic",
                                   model_id="claude-sonnet-5-5")}
        return script[str(kwargs["layer"])]

    with patch("refcheck.stages.verify_claims.cascade.run_layer", fake_run_layer), \
            patch("refcheck.stages.verify_claims.escalation.resolve_role", fake_resolve), \
            patch("refcheck.stages.verify_claims.escalation.role_candidates", fake_candidates):
        out = await run_cascade(make_ctx(), None, _ON, deadline=time.monotonic() + 100)
    assert models == [None, "claude-sonnet-5-5"]
    assert out.consensus_type == "confirmed" and not out.needs_review


async def test_failed_cross_check_strict_policy_keeps_the_flag(
        monkeypatch: "pytest.MonkeyPatch") -> None:
    monkeypatch.setenv("REFCHECK_DISPUTE_POLICY", "strict")
    out, _ = await _route({"verifier": [haiku("not_supported")],
                           "confirm": [layer("confirm", error="cost limit reached: cap")]})
    assert out.verdict == "not_supported" and out.consensus_type == "verifier_unconfirmed"
