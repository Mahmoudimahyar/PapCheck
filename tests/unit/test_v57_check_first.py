"""V5.7 #9: "check first" triage of supported verdicts (notes / review only, never the verdict).

Regression (V5.6 gold dive, 281 pairs): 7 gold partials were shown as plain "supported";
6 of them carried a weak signal against the verdict that nothing surfaced - a low screen
finding_stated, only secondary / future-work supporting quotes, a re-check that overturned
a partial first run, a slot-audit trigger that was cleared. Synthetic text only.
"""

import time
from unittest.mock import patch

import pytest

from refcheck.models.verification import VerificationResult
from refcheck.stages.generate_report.result_signals import (
    check_first,
    missed_problem_reasons,
    result_signals,
)
from refcheck.stages.verify_claims.calibration import ScreenThresholds
from refcheck.stages.verify_claims.cascade import CascadeOutcome
from refcheck.stages.verify_claims.cascade_helpers import build_result
from refcheck.stages.verify_claims.check_first import (
    CHECK_FIRST_OPENING,
    SLOT_AUDIT_LAYER,
    check_first_outcome,
    check_first_reasons,
    recheck_flip,
    secondary_only,
    with_check_first,
)
from refcheck.stages.verify_claims.layers import LayerResult, ValidatedQuote
from refcheck.stages.verify_claims.slot_apply import SLOT_LAYER
from tests.unit.verify_fakes import layer, make_ctx, screen

SECONDARY = "Drug X lowered IL-6 in earlier mouse studies [12, 13]."
FUTURE = "Future studies should test whether drug X lowers IL-6 in other models."
OWN = "Drug X reduced IL-6 levels by 40% compared with vehicle (p < 0.01)."


def _with_quotes(lay: LayerResult, *texts: str) -> LayerResult:
    quotes = [ValidatedQuote(passage_id="P1", text=t, role="supports", similarity=1.0,
                             source_span=t) for t in texts]
    return lay.model_copy(update={"validated_quotes": quotes})


def _outcome(*layers: LayerResult) -> CascadeOutcome:
    label = layers[-1]
    return CascadeOutcome(verdict=label.verdict or "", label_layer=label, decided_by="verifier",
                          consensus_type="verifier", tier=2, layers=list(layers),
                          layer_path=["screen", *(lay.layer for lay in layers)])


def test_a_low_screen_finding_stated_is_a_reason() -> None:
    out = _outcome(layer("verifier"))
    assert check_first_reasons(out, screen(0.35)) == []
    assert check_first_reasons(out, None) == []
    (reason,) = check_first_reasons(out, screen(0.2))
    assert "screen" in reason and "(0.20)" in reason
    failed = screen(0.2).model_copy(update={"error": "timeout"})
    assert check_first_reasons(out, failed) == []
    assert check_first_reasons(out, screen(0.2, refused=("finding_stated",))) == []


@pytest.mark.parametrize(("texts", "flagged"), [
    ((SECONDARY,), True), ((FUTURE,), True), ((SECONDARY, FUTURE), True),
    ((SECONDARY, OWN), False), ((OWN,), False), ((), False),
])
def test_secondary_or_future_only_supporting_quotes(texts: tuple[str, ...], flagged: bool) -> None:
    lay = _with_quotes(layer("verifier"), *texts)
    assert secondary_only(lay) is flagged
    assert bool(check_first_reasons(_outcome(lay), screen(0.9))) is flagged


def test_a_marker_right_after_the_quote_counts_as_secondary() -> None:
    quote = ValidatedQuote(passage_id="P1", text="Drug X lowered IL-6 in mice", role="supports",
                           source_span="Drug X lowered IL-6 in mice", source_after=" [7].")
    assert secondary_only(layer("verifier").model_copy(update={"validated_quotes": [quote]}))


def test_a_recheck_that_overturned_an_unquoted_first_run_is_a_reason() -> None:
    first = layer("verifier", "partially_supported", role_quote="closest")
    flip = [first, layer("verifier_recheck", "supported")]
    assert recheck_flip(flip) == "partially_supported"
    (reason,) = check_first_reasons(_outcome(*flip), screen(0.9))
    assert "'partially supported'" in reason
    overturn = [layer("verifier", "not_supported", supports=False),
                layer("verifier_recheck", "supported"), layer("confirm", "supported")]
    assert recheck_flip(overturn) == "not_supported"
    assert recheck_flip([layer("verifier", "supported")]) is None
    assert recheck_flip([first, layer("verifier_recheck", "partially_supported")]) is None


def test_a_flip_whose_first_run_had_a_supporting_quote_is_no_reason() -> None:
    # V5.6 gold: all 12 such flips were right; the one wrong flip had no supports quote.
    flip = [layer("verifier", "partially_supported"), layer("verifier_recheck", "supported")]
    assert recheck_flip(flip) is None and check_first_reasons(_outcome(*flip), screen(0.9)) == []


def test_a_slot_audit_that_left_the_verdict_supported_is_a_reason() -> None:
    assert SLOT_AUDIT_LAYER == SLOT_LAYER
    cleared = layer("verifier").model_copy(update={"layer": SLOT_LAYER, "role": "adjudicator"})
    out = _outcome(layer("verifier"), cleared).model_copy(
        update={"label_layer": layer("verifier")})
    (reason,) = check_first_reasons(out, screen(0.9))
    assert reason.endswith("was cleared")
    failed = cleared.model_copy(update={"output": None, "error": "timeout"})
    out = out.model_copy(update={"layers": [layer("verifier"), failed]})
    assert check_first_reasons(out, screen(0.9))[0].endswith("could not be checked")


def test_only_supported_verdicts_are_triaged() -> None:
    partial = _outcome(layer("verifier", "partially_supported"))
    assert check_first_reasons(partial, screen(0.1)) == []
    assert with_check_first(partial, ["anything"]) == partial


def test_the_note_and_review_flag_never_change_the_verdict(monkeypatch: pytest.MonkeyPatch,
                                                         ) -> None:
    monkeypatch.delenv("REFCHECK_V57_DISABLE", raising=False)
    out = _outcome(layer("verifier"))
    flagged = with_check_first(out, ["reason one", "reason two"])
    assert flagged.verdict == "supported" and flagged.needs_review
    assert flagged.notes[-1].startswith(CHECK_FIRST_OPENING)
    assert with_check_first(flagged, ["reason one", "reason two"]) == flagged  # idempotent
    assert with_check_first(out, []) == out
    monkeypatch.setenv("REFCHECK_V57_DISABLE", "3,9")
    assert with_check_first(out, ["reason one"]) == out


async def test_the_triage_makes_no_llm_call_while_the_probe_is_off(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REFCHECK_SLOT_PROBE", raising=False)
    monkeypatch.delenv("REFCHECK_V57_DISABLE", raising=False)

    async def no_call(*args: object, **kwargs: object) -> None:
        raise AssertionError("no LLM call expected")

    with patch("refcheck.stages.verify_claims.slot_probe_call.call_llm_raw", no_call):
        out = await check_first_outcome(make_ctx(), screen(0.1), _outcome(layer("verifier")),
                                        None, time.monotonic() + 60)
    assert out.verdict == "supported" and out.needs_review and out.layer_path[-1] == "verifier"


async def _result(monkeypatch: pytest.MonkeyPatch) -> VerificationResult:
    monkeypatch.delenv("REFCHECK_V57_DISABLE", raising=False)
    monkeypatch.delenv("REFCHECK_SLOT_PROBE", raising=False)
    ctx = make_ctx()
    flip = _outcome(layer("verifier", "partially_supported", role_quote="closest"),
                    layer("verifier_recheck"))
    out = await check_first_outcome(ctx, screen(0.2), flip, None, time.monotonic() + 60)
    return build_result(ctx, screen(0.2), out, ScreenThresholds(), 1)


async def test_signals_parse_the_verify_stage_note(monkeypatch: pytest.MonkeyPatch) -> None:
    v = await _result(monkeypatch)
    assert v.verdict == "supported" and v.needs_user_review and check_first(v)
    reasons = result_signals(v).check_first_reasons
    assert len(reasons) == 2 and "(0.20)" in reasons[0] and "re-check" in reasons[1]
    assert missed_problem_reasons(v.reasoning) == reasons


async def test_a_reviewed_or_partial_result_is_not_check_first_by_the_note(
        monkeypatch: pytest.MonkeyPatch) -> None:
    v = await _result(monkeypatch)
    assert not check_first(v.model_copy(update={"user_override": True}))
    partial = v.model_copy(update={"verdict": "partially_supported", "consensus_type": "verifier"})
    assert not check_first(partial) and result_signals(partial).check_first_reasons == []
