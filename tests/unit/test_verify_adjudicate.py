"""Element adjudicator: the call, failures, schema and prompt (rules: *_rules.py)."""

import time

import pytest
import tiktoken

from refcheck.llm import CostTracker
from refcheck.llm.errors import LLMRefusalError
from refcheck.llm.schema import strict_json_schema
from refcheck.llm.templates import render_template
from refcheck.models.adjudication import AdjudicateOutput, ElementCheck
from refcheck.stages.verify_claims.adjudicate import adjudicate_enabled, run_adjudication
from refcheck.stages.verify_claims.adjudicate_prompt import (
    TEMPLATE,
    adjudicate_system_variables,
    adjudicate_user_variables,
)
from tests.unit.adjudicate_fakes import (
    ABSENT,
    COCITED,
    COCITED_QUOTE,
    FRAMING,
    STATED,
    WORDING,
    answer_all,
    ctx_with_cocited,
    fake_call,
    output,
)

_LATER = time.monotonic() + 1000


def test_switch_defaults_on_and_reads_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REFCHECK_ADJUDICATE", raising=False)
    assert adjudicate_enabled()
    for value in ("off", "0", "false", "OFF"):
        monkeypatch.setenv("REFCHECK_ADJUDICATE", value)
        assert not adjudicate_enabled()
    monkeypatch.setenv("REFCHECK_ADJUDICATE", "on")
    assert adjudicate_enabled()


async def test_run_adjudication_records_the_call() -> None:
    ctx, calls = ctx_with_cocited(), list[dict[str, object]]()
    with fake_call(answer_all(STATED, COCITED, ABSENT), calls):
        adj = await run_adjudication(ctx, ctx.pack, "standard", ["a", "b", "c"], None, _LATER)
    assert adj.ok and [d.cleared for d in adj.decisions] == [True, True, False]
    assert adj.meta.model_id == "claude-haiku-5-5" and adj.meta.cost_usd == 0.0001
    assert adj.meta.role == "adjudicator" and adj.meta.layer == "adjudicate"
    call = calls[0]
    assert call["template"] == TEMPLATE and call["role"] == "adjudicator"
    assert call["task"] == "verify_adjudicate" and call["system_template"] == TEMPLATE


async def test_an_answer_for_one_element_never_clears_another() -> None:
    ctx = ctx_with_cocited()
    elements = ["two-stage scheme", "in elderly runners"]
    twice = output(["two-stage scheme", "two-stage scheme"], [FRAMING, FRAMING])
    with fake_call(lambda asked: twice):
        adj = await run_adjudication(ctx, ctx.pack, "standard", elements, None, _LATER)
    assert [d.element for d in adj.cleared] == ["two-stage scheme"]
    assert [d.element for d in adj.surviving] == ["in elderly runners"]
    assert adj.surviving[0].category == "absent"


@pytest.mark.parametrize("error", [LLMRefusalError("refused", "claude-haiku-5-5"),
                                   TimeoutError("slow")])
async def test_failures_are_recorded_never_raised(error: Exception) -> None:
    ctx = ctx_with_cocited()
    with fake_call(lambda elements: error):
        adj = await run_adjudication(ctx, ctx.pack, "standard", ["a"], None, _LATER)
    assert not adj.ok and adj.meta.error and not adj.decisions


async def test_budget_and_time_skip_the_call() -> None:
    ctx, calls = ctx_with_cocited(), list[dict[str, object]]()
    with fake_call(answer_all(WORDING), calls):
        spent = await run_adjudication(ctx, ctx.pack, "standard", ["a"],
                                       CostTracker(max_cost=0.0), _LATER)
        late = await run_adjudication(ctx, ctx.pack, "standard", ["a"], None,
                                      time.monotonic() + 1)
    assert not calls
    assert spent.meta.error_kind == "budget" and late.meta.error_kind == "timeout"


def test_output_schema_is_strict_and_claude_safe() -> None:
    schema = strict_json_schema(AdjudicateOutput)
    assert schema is not None and schema["additionalProperties"] is False
    assert schema["required"] == ["elements", "explanation"]
    item = schema["properties"]["elements"]["items"]  # type: ignore[index]
    assert sorted(item["required"]) == ["category", "element", "note", "passage_id", "quote"]
    assert "reasoning" not in str(schema) and "thinking" not in str(schema)
    with pytest.raises(ValueError):
        ElementCheck.model_validate({"element": "x", "category": "maybe", "passage_id": None,
                                     "quote": None, "note": ""})


def test_prompt_renders_compact_system_and_full_user_part() -> None:
    system = render_template(TEMPLATE, adjudicate_system_variables())
    tokens = len(tiktoken.get_encoding("o200k_base").encode(system))
    assert tokens <= 1200, tokens
    for needed in ("cocited_share", "author_framing_or_example", "overliteral_wording",
                   "'widely'", "title only", "broadened", "stays wording (G4)"):
        assert needed in system
    assert '"may"' not in system  # a one-step hedge shift is wording (G4), not overstated
    ctx = ctx_with_cocited()
    user = render_template(TEMPLATE, adjudicate_user_variables(
        ctx.claim, ctx, ctx.pack, "standard", ["IL-6 reduction", "in mice"]))
    assert "[P1]" in user and "1. IL-6 reduction" in user and "2. in mice" in user
    assert "[2] Gel Q in wounds — Abstract:" in user and "[3] Drug X lowers" in user
    assert "(title only)" in user and COCITED_QUOTE in user
