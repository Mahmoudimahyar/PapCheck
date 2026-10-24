"""L1 screen: Decisions input, predicates, s, auto-clear gates (V5 cascade)."""

from unittest.mock import AsyncMock, patch

import pytest

from refcheck.llm import DecisionAnswer, DecisionError, DecisionResult
from refcheck.stages.verify_claims.calibration import ScreenThresholds
from refcheck.stages.verify_claims.screen import (
    SCREEN_PREDICATES,
    build_screen_input,
    clear_gates,
    combine,
    run_screen,
    screen_conflicts,
    screen_questions,
)
from tests.unit.verify_fakes import make_claim, make_ctx, screen

_ON = ScreenThresholds()


def _decision(probs: dict[str, float], refused: tuple[str, ...] = ()) -> DecisionResult:
    answers = {n: DecisionAnswer(name=n, type="predicate", probability=p)
               for n, p in probs.items()}
    answers.update({n: DecisionAnswer(name=n, type="refusal", refused=True) for n in refused})
    return DecisionResult(model="gpt-6-luna-decisions", answers=answers, input_tokens=4000,
                          latency_ms=180, cost_usd=0.0004, requests=1)


def test_six_predicates_with_strict_conflict_wording() -> None:
    questions = screen_questions()
    assert [q.name for q in questions] == list(SCREEN_PREDICATES)
    assert all(q.type == "predicate" for q in questions)
    conflicts = next(q for q in questions if q.name == "finding_conflicts")
    assert "same population, intervention and outcome" in conflicts.instructions


def test_screen_input_layout() -> None:
    ctx = make_ctx(make_claim("Drug X reduces inflammation [4].", co_cited=3))
    text = build_screen_input(ctx)
    assert text.startswith("CLAIM (from an unpublished manuscript; citation markers removed): "
                           "Drug X reduces inflammation.")
    assert "OTHER REFERENCES CITED IN THIS SENTENCE: 2" in text
    assert "CITED SOURCE: Drug X in mice (Smith J, 2020)" in text
    assert text.index("SOURCE PASSAGES") < text.index("[A] Abstract:") < text.index("[P1]")


def test_combine_is_min_of_support_and_inverted_problems() -> None:
    probs = {"topic_match": 1.0, "finding_stated": 0.98, "evidence_sufficient": 0.99,
             "finding_conflicts": 0.1, "claim_overreaches": 0.05}
    assert combine(probs) == pytest.approx(0.9)
    assert combine({}) is None


async def test_run_screen_parses_answers() -> None:
    probs = {"topic_match": 1.0, "finding_stated": 0.99, "evidence_sufficient": 1.0,
             "finding_conflicts": 0.0, "claim_overreaches": 0.0}
    fake = AsyncMock(return_value=_decision(probs, ("contains_instructions",)))
    with patch("refcheck.stages.verify_claims.screen.decide", fake):
        result = await run_screen(make_ctx())
    assert result.ok and result.s == pytest.approx(0.99)
    assert result.p_problem == pytest.approx(0.01)
    assert result.refused == ["contains_instructions"]
    assert result.model_display == "Decisions API · gpt-6-luna"
    assert fake.await_args is not None and fake.await_args.kwargs["role"] == "screen"


async def test_run_screen_error_is_recorded_not_raised() -> None:
    fake = AsyncMock(side_effect=DecisionError("boom", "transient"))
    with patch("refcheck.stages.verify_claims.screen.decide", fake):
        result = await run_screen(make_ctx())
    assert not result.ok and result.error is not None and result.s is None


class TestClearGates:
    def test_all_gates_pass(self) -> None:
        ctx = make_ctx()
        eligible, failed = clear_gates(ctx.claim, ctx, screen(0.99), _ON)
        assert eligible and failed == []

    def test_quantitative_claim_never_cleared(self) -> None:
        ctx = make_ctx(make_claim("Drug X reduced inflammation by 40% in mice."))
        eligible, failed = clear_gates(ctx.claim, ctx, screen(1.0), _ON)
        assert not eligible and "numeric_claim" in failed

    def test_abstract_only_never_cleared(self) -> None:
        ctx = make_ctx(coverage="abstract_only")
        eligible, failed = clear_gates(ctx.claim, ctx, screen(1.0), _ON)
        assert not eligible and "abstract_only" in failed

    @pytest.mark.parametrize(("claim_kwargs", "gate"), [
        ({"text": "Drug X does not reduce inflammation."}, "negation"),
        ({"text": "Drug X works " + "very " * 60}, "too_long"),
        ({"claim_type": "contrast"}, "contrast"),
    ])
    def test_claim_shape_gates(self, claim_kwargs: dict[str, str], gate: str) -> None:
        ctx = make_ctx(make_claim(**claim_kwargs))  # type: ignore[arg-type]
        eligible, failed = clear_gates(ctx.claim, ctx, screen(1.0), _ON)
        assert not eligible and gate in failed

    def test_screen_answer_gates(self) -> None:
        ctx = make_ctx()
        for result, gate in [
            (screen(0.96), "below_threshold"),
            (screen(1.0, injection=0.3), "injection"),
            (screen(1.0, refused=("claim_overreaches",)), "refusal"),
            (None, "screen_unavailable"),
        ]:
            eligible, failed = clear_gates(ctx.claim, ctx, result, _ON)
            assert not eligible and gate in failed

    def test_disabled_screen(self) -> None:
        ctx = make_ctx()
        off = _ON.model_copy(update={"enabled": False})
        assert "screen_disabled" in clear_gates(ctx.claim, ctx, screen(1.0), off)[1]

    def test_auto_clear_off_blocks_clearance_but_keeps_conflicts(self) -> None:
        ctx = make_ctx()
        no_clear = _ON.model_copy(update={"auto_clear": False})
        eligible, failed = clear_gates(ctx.claim, ctx, screen(1.0), no_clear)
        assert not eligible and failed == ["auto_clear_off"]
        assert screen_conflicts(screen(0.5, conflicts=0.6), no_clear)


def test_screen_conflicts() -> None:
    assert not screen_conflicts(None, _ON)
    assert not screen_conflicts(screen(0.5), _ON)
    assert screen_conflicts(screen(0.5, conflicts=0.6), _ON)
    assert screen_conflicts(screen(0.5, topic=0.2), _ON)
    strict = _ON.model_copy(update={"policy": {"t_contra": 0.2}})
    assert screen_conflicts(screen(0.5, conflicts=0.3), strict)
