"""Decisions API wrapper: parsing, refusals, chunking, errors, cost."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from refcheck.llm.cost_tracker import CostTracker
from refcheck.llm.decisions import (
    DecisionError,
    DecisionQuestion,
    decide,
    parse_answers,
)
from refcheck.llm.roles import unavailable_models
from tests.unit.llm_fakes import (
    FAKE_OPENAI,
    choice,
    decision_response,
    isolated_llm_env,
    not_found_error,
    predicate,
    rate_limit_error,
    refusal,
)

_PATCH = "refcheck.llm.decisions._sync_decisions"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    yield from isolated_llm_env(monkeypatch, tmp_path)


def _questions(n: int) -> list[DecisionQuestion]:
    return [DecisionQuestion(name=f"q{i}", instructions=f"Question {i}?") for i in range(n)]


def _echo(kwargs: dict[str, object]) -> object:
    """Fake API: answers every predicate in the request with 0.5."""
    questions = kwargs["questions"]
    assert isinstance(questions, list)
    return decision_response([predicate(q["name"], 0.5) for q in questions], input_tokens=1000)


class TestParsing:
    def test_predicate_choice_refusal_and_missing(self) -> None:
        qs = [
            DecisionQuestion(name="topic_match", instructions="Same subject?"),
            DecisionQuestion(name="label", instructions="Pick", type="choice",
                             choices=["yes", "no"]),
            DecisionQuestion(name="vague", instructions="x?"),
            DecisionQuestion(name="dropped", instructions="Never answered?"),
        ]
        response = decision_response([
            predicate("topic_match", 0.97), choice("label", "yes", {"yes": 0.8, "no": 0.2}),
            refusal("vague"),
        ])
        answers = parse_answers(response, qs)
        assert answers["topic_match"].probability == 0.97
        assert answers["label"].choice == "yes"
        assert answers["label"].probabilities == {"yes": 0.8, "no": 0.2}
        assert answers["vague"].refused and answers["vague"].probability is None
        assert answers["dropped"].refused

    def test_unnamed_answers_map_by_position(self) -> None:
        answers = parse_answers(decision_response([predicate(None, 1.0)]), _questions(1))
        assert answers["q0"].probability == 1.0

    def test_boolean_choice_values(self) -> None:
        qs = [DecisionQuestion(name="b", instructions="?", type="choice",
                               choices=["true", "false"])]
        answers = parse_answers(decision_response([choice("b", True, {True: 0.9, False: 0.1})]),
                                qs)
        assert answers["b"].choice == "true" and answers["b"].probability == 0.9

    def test_choice_question_validation(self) -> None:
        with pytest.raises(ValidationError):
            DecisionQuestion(name="c", instructions="?", type="choice", choices=["only"])
        with pytest.raises(ValidationError):
            DecisionQuestion(name="c", instructions="?", type="choice", choices=["a", "a"])


class TestDecide:
    async def test_request_shape_result_and_cost(self) -> None:
        tracker = CostTracker()
        mock = MagicMock(return_value=decision_response(
            [predicate("q0", 1.0), refusal("q1")], input_tokens=5_000, cached=3_000))
        with patch(_PATCH, mock):
            result = await decide("CLAIM: x", _questions(2), cost_tracker=tracker)
        kwargs = mock.call_args.args[0]
        assert kwargs["model"] == "openai/gpt-6-luna"
        assert kwargs["api_key"] == FAKE_OPENAI
        assert kwargs["questions"][0] == {"type": "predicate", "name": "q0",
                                          "instructions": "Question 0?"}
        assert result.model == "gpt-6-luna-decisions"
        assert result.probability("q0") == 1.0 and result.probability("q1") is None
        assert result.refused == ["q1"]
        # input tokens x $0.10/M, cached tokens are NOT discounted
        assert result.cost_usd == pytest.approx(5_000 * 0.10 / 1e6)
        assert tracker.records[0].role == "screen" and tracker.records[0].kind == "decision"

    async def test_more_than_128_questions_are_chunked(self) -> None:
        mock = MagicMock(side_effect=_echo)
        with patch(_PATCH, mock):
            result = await decide("text", _questions(200))
        sizes = sorted(len(c.args[0]["questions"]) for c in mock.call_args_list)
        assert sizes == [72, 128]
        assert len(result.answers) == 200 and result.requests == 2
        assert result.input_tokens == 2000

    async def test_rate_limit_is_retried(self) -> None:
        mock = MagicMock(side_effect=[rate_limit_error(), _echo({"questions": [
            {"name": "q0"}]})])
        with patch(_PATCH, mock):
            result = await decide("text", _questions(1))
        assert result.probability("q0") == 0.5 and mock.call_count == 2

    async def test_api_error_raises_decision_error_and_disables_model(self) -> None:
        tracker = CostTracker()
        with patch(_PATCH, MagicMock(side_effect=not_found_error())), \
                pytest.raises(DecisionError) as info:
            await decide("text", _questions(1), cost_tracker=tracker)
        assert info.value.kind == "not_found"
        assert "gpt-6-luna-decisions" in unavailable_models()
        assert tracker.summary().failed_calls == 1

    async def test_duplicate_names_rejected_locally(self) -> None:
        qs = [DecisionQuestion(name="a", instructions="?"),
              DecisionQuestion(name="a", instructions="??")]
        with pytest.raises(DecisionError) as info:
            await decide("text", qs)
        assert info.value.kind == "bad_request"

    async def test_empty_questions_rejected(self) -> None:
        with pytest.raises(DecisionError):
            await decide("text", [])

    async def test_screen_disabled_raises_unavailable(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("REFCHECK_SCREEN_ENABLED", "0")
        mock = MagicMock()
        with patch(_PATCH, mock), pytest.raises(DecisionError) as info:
            await decide("text", _questions(1))
        assert info.value.kind == "unavailable"
        mock.assert_not_called()

    async def test_malformed_response_is_decision_error(self) -> None:
        bad = MagicMock()
        bad.answers = 42  # not iterable
        with patch(_PATCH, MagicMock(return_value=bad)), pytest.raises(DecisionError) as info:
            await decide("text", _questions(1))
        assert info.value.kind == "invalid_output"
