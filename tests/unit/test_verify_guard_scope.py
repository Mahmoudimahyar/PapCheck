"""Guards only where they cleared something; a "supported" that still lists elements is unusual."""

import time
from unittest.mock import patch

import pytest

from refcheck.stages.verify_claims.calibration import ScreenThresholds
from refcheck.stages.verify_claims.cascade import CascadeOutcome, run_cascade
from refcheck.stages.verify_claims.cascade_helpers import build_result
from refcheck.stages.verify_claims.layers import LayerResult
from refcheck.stages.verify_claims.partial_fields import partial_fields, uncovered_elements
from refcheck.stages.verify_claims.retriever import EvidencePack
from refcheck.stages.verify_claims.screen import ScreenResult
from refcheck.stages.verify_claims.verifier_helpers import PairContext
from tests.unit.verify_fakes import layer, make_ctx, screen

_ON = ScreenThresholds()
_FOUND = "body weight did not differ between the groups"  # in the fake full text
_ABSENT = "restored limb function"


def typed(lay: LayerResult, *elements: str, notes: tuple[str, ...] = (),
          ptype: str = "missing_element") -> LayerResult:
    assert lay.output is not None
    out = lay.output.model_copy(update={"unsupported_elements": list(elements),
                                        "benign_notes": list(notes), "partial_type": ptype})
    return lay.model_copy(update={"output": out})


def _partial(*elements: str) -> LayerResult:
    return typed(layer("verifier", "partially_supported", severity="minor"), *elements)


def test_partial_keeps_the_recheck_guard_only_for_an_element_no_longer_listed() -> None:
    lay = _partial(_ABSENT)
    f = partial_fields("partially_supported", lay, [lay], "full_text", ["evidence_recheck"],
                       recheck_cleared=[_FOUND])
    assert f.guards_applied == ["evidence_recheck"] and len(f.notes) == 1
    assert f.notes[0].startswith("Evidence re-check: cleared part of the concern")
    assert f"'{_FOUND}'" in f.notes[0] and "missed" not in f.notes[0]
    # Still listed (reworded): the re-check cleared nothing.
    still = partial_fields("partially_supported", _partial("Body weight did not differ"),
                           [lay], "full_text", ["evidence_recheck"],
                           recheck_cleared=["body weight did not differ"])
    assert still.guards_applied == [] and still.notes == []
    # Only the verdict moved (negative -> partial), no element found: no clearing claimed.
    moved = partial_fields("partially_supported", lay, [lay], "full_text", ["evidence_recheck"])
    assert moved.guards_applied == [] and moved.notes == []


@pytest.mark.parametrize("verdict", ["not_supported", "contradicted", "not_relevant"])
def test_negative_verdict_never_claims_a_clearing(verdict: str) -> None:
    lay = typed(layer("verifier", verdict, role_quote="closest"), _ABSENT,
                notes=("cocited_share", "overliteral_wording"), ptype="tangential_source")
    f = partial_fields(verdict, lay, [lay], "full_text", ["evidence_recheck"],
                       recheck_cleared=[_FOUND])
    assert f.guards_applied == [] and f.notes == [] and f.partial_type == "tangential_source"


def test_undecided_verdict_gets_no_fields() -> None:
    lay = typed(layer("verifier", "insufficient_evidence"), _ABSENT, notes=("cocited_share",))
    f = partial_fields("insufficient_evidence", lay, [lay], "full_text", ["evidence_recheck"])
    assert f.guards_applied == [] and f.notes == [] and f.partial_type is None


def test_supported_keeps_only_elements_no_benign_note_dismisses() -> None:
    bare = typed(layer("verifier"), _ABSENT)
    assert uncovered_elements(bare.output) == [_ABSENT]
    f = partial_fields("supported", bare, [bare], "full_text", [])
    assert f.unsupported_elements == [_ABSENT] and f.partial_type is None
    noted = typed(layer("verifier"), _ABSENT, notes=("overliteral_wording",))
    f = partial_fields("supported", noted, [noted], "full_text", [])
    assert f.unsupported_elements == [] and f.guards_applied == ["overliteral_wording"]
    secondary = typed(layer("verifier"), _ABSENT, notes=("secondary_source",))
    assert uncovered_elements(secondary.output) == [_ABSENT]  # a note only, not a guard


async def _route(script: dict[str, list[LayerResult]], scr: ScreenResult | None = None,
                 ) -> tuple[list[str], CascadeOutcome, PairContext]:
    calls: list[str] = []
    ctx = make_ctx()
    ctx.use_embeddings = False  # BM25 only: no embedding call in unit tests

    async def fake_run_layer(role: str, pack: EvidencePack, claim: object, c: object,
                             template: str, **kwargs: object) -> LayerResult:
        calls.append(str(kwargs["layer"]))
        result = script[str(kwargs["layer"])].pop(0)
        return result.model_copy(update={"pack_kind": kwargs["pack_kind"]})

    with patch("refcheck.stages.verify_claims.cascade.run_layer", fake_run_layer):
        out = await run_cascade(ctx, scr, _ON, deadline=time.monotonic() + 100)
    return calls, out, ctx


def _confirm(verdict: str = "supported") -> LayerResult:
    return layer("confirm", verdict, provider="anthropic", model_id="claude-sonnet-5-5",
                 role_quote="supports" if verdict == "supported" else "closest")


async def test_supported_with_uncovered_elements_is_cross_checked_and_keeps_them() -> None:
    calls, out, ctx = await _route({"verifier": [typed(layer("verifier"), _ABSENT)],
                                    "confirm": [_confirm()]}, scr=screen(0.99))
    assert out.clear_eligible and calls == ["verifier", "confirm"]
    assert out.verdict == "supported" and out.decided_by == "verifier" and out.needs_review
    assert any(f"'{_ABSENT}'" in note for note in out.notes)
    result = build_result(ctx, None, out, _ON, 1)
    assert result.unsupported_elements == [_ABSENT] and result.needs_user_review


async def test_supported_with_a_benign_note_stays_final() -> None:
    # A cocited_share note reaches routing only when a co-cited abstract was shown
    # (layers.checked_notes, test_verify_layers); the fake layer stands for that case.
    lay = typed(layer("verifier"), _ABSENT, notes=("cocited_share",))
    calls, out, _ = await _route({"verifier": [lay]}, scr=screen(0.99))
    assert calls == ["verifier"] and out.consensus_type == "screen_clear"


async def test_rechecked_supported_with_elements_is_cross_checked_once() -> None:
    second = typed(layer("verifier_recheck"), _ABSENT)
    calls, out, _ = await _route({"verifier": [_partial(_FOUND)], "verifier_recheck": [second],
                                  "confirm": [_confirm("not_supported")]})
    assert calls == ["verifier", "verifier_recheck", "confirm"]
    assert out.verdict == "partially_supported" and out.consensus_type == "disputed"


async def test_partial_after_the_recheck_names_what_it_found() -> None:
    calls, out, ctx = await _route({"verifier": [_partial(_FOUND, _ABSENT)],
                                    "verifier_recheck": [typed(layer(
                                        "verifier_recheck", "partially_supported",
                                        severity="minor"), _ABSENT)]})
    assert calls == ["verifier", "verifier_recheck"] and out.recheck_cleared == [_FOUND]
    result = build_result(ctx, None, out, _ON, 1)
    assert result.verdict == "partially_supported"
    assert result.guards_applied == ["evidence_recheck"]
    assert result.unsupported_elements == [_ABSENT]
    assert "cleared part of the concern" in result.reasoning
    assert "found the passage the first check missed" not in result.reasoning


async def test_softened_dispute_after_a_negative_recheck_claims_no_clearing() -> None:
    """A still-negative re-run that only rewords an element clears nothing, even when the
    cross-check softens the shown verdict to partial."""
    first = typed(layer("verifier", "not_supported", role_quote="closest"), _FOUND, _ABSENT,
                  ptype="tangential_source")
    second = typed(layer("verifier_recheck", "not_supported", role_quote="closest"),
                   "recovery of motor function in the limb", ptype="tangential_source")
    calls, out, ctx = await _route({"verifier": [first], "verifier_recheck": [second],
                                    "confirm": [_confirm()]})
    assert calls == ["verifier", "verifier_recheck", "confirm"]
    assert out.guards == [] and out.recheck_cleared == []
    result = build_result(ctx, None, out, _ON, 1)
    assert result.verdict == "partially_supported" and result.guards_applied == []
    assert "Evidence re-check" not in result.reasoning


async def test_unusual_supported_with_a_partial_cross_check_shows_the_partial() -> None:
    confirm = typed(layer("confirm", "partially_supported", provider="anthropic",
                          model_id="claude-sonnet-5-5", severity="minor"), _ABSENT)
    calls, out, ctx = await _route({"verifier": [typed(layer("verifier"), _ABSENT)],
                                    "confirm": [confirm]})
    assert calls == ["verifier", "confirm"] and out.label_layer is not None
    assert out.verdict == "partially_supported" and out.consensus_type == "disputed"
    assert out.label_layer.layer == "confirm" and out.needs_review
    assert "Both models found support" not in " ".join(out.notes)
    assert "verifier said supported" in out.notes[0] and "Cross-check:" in out.notes[0]
    result = build_result(ctx, None, out, _ON, 1)
    assert result.verdict == "partially_supported" and result.partial_type == "missing_element"
