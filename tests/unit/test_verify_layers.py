"""L2/L3/L4 layer calls: prompts, quote validation and failure handling (V5)."""

from unittest.mock import AsyncMock, patch

import pytest

from refcheck.llm import CostLimitExceededError, LLMCallError, NoModelAvailableError
from refcheck.llm.schema import strict_json_schema
from refcheck.llm.templates import render_template
from refcheck.models.verification import Dismissal, JudgeOutput
from refcheck.stages.verify_claims.cocited import co_cited_ref
from refcheck.stages.verify_claims.layers import (
    axis_of,
    layer_variables,
    run_layer,
    validate_output_quotes,
)
from refcheck.stages.verify_claims.partial_fields import uncovered_elements
from refcheck.stages.verify_claims.taxonomy_prompt import system_variables
from tests.unit.verify_fakes import (
    ABSTRACT,
    RESULT_TEXT,
    judge_output,
    llm_result,
    make_claim,
    make_ctx,
    make_pack,
)

_PATCH = "refcheck.stages.verify_claims.layers.call_llm_raw"


def test_axis() -> None:
    assert axis_of("supported") == axis_of("partially_supported") == "positive"
    assert axis_of("not_supported") == axis_of("contradicted") == axis_of("not_relevant") \
        == "negative"
    assert axis_of("insufficient_evidence") is None and axis_of(None) is None


def test_judge_output_schema_is_strict_and_lenient() -> None:
    schema = strict_json_schema(JudgeOutput)
    assert schema is not None
    required = schema["required"]
    assert isinstance(required, list)
    assert set(required) == {
        "verdict", "severity", "problem_type", "confidence", "quotes", "explanation", "missing",
        "partial_type", "unsupported_elements", "benign_notes", "dismissed"}
    assert schema["additionalProperties"] is False and "reasoning" not in str(schema)
    props = schema["properties"]
    assert isinstance(props, dict)
    assert "coverage_limited" in props["partial_type"]["enum"]
    assert "none" in props["partial_type"]["enum"]
    assert props["unsupported_elements"] == {"type": "array", "items": {"type": "string"}}
    notes = ["cocited_share", "author_framing_or_example", "overliteral_wording",
             "secondary_source"]
    assert props["benign_notes"]["items"]["enum"] == notes
    quote = props["quotes"]["items"]
    assert set(quote["required"]) == {"passage_id", "text", "role", "states"}
    assert quote["properties"]["role"]["enum"] == ["supports", "contradicts", "closest"]
    dismissal = props["dismissed"]["items"]
    assert set(dismissal["required"]) == {"element", "guard", "passage_id", "quote"}
    assert dismissal["additionalProperties"] is False
    assert dismissal["properties"]["guard"]["enum"] == notes
    out = judge_output("supported", [("P1", "a", "supports")] * 5, confidence=1.7)
    assert out.confidence == 1.0 and len(out.quotes) == 3
    assert out.partial_type == "none" and out.unsupported_elements == []  # older caches parse
    long = JudgeOutput.model_validate({**out.model_dump(), "unsupported_elements":
                                       [" x " * 100, "", *(f"e{i}" for i in range(7))]})
    assert len(long.unsupported_elements) == 5 and len(long.unsupported_elements[0]) <= 160


@pytest.mark.parametrize("template", ["verify_claim", "judge_claim"])
def test_prompt_puts_passages_first_and_claim_last(template: str) -> None:
    ctx = make_ctx(make_claim(co_cited=3))
    user = render_template(template, layer_variables(ctx.claim, ctx, ctx.pack, "standard"))
    assert user.index("[A] Abstract:") < user.index("[P1]") < user.index("CLAIM TO CHECK")
    assert "cites 3 references together" in user
    system = render_template(template, system_variables())
    assert "non-significant 12% reduction" in system and "NOT contradicted" in system
    assert '"explanation"' in system and '"reasoning"' not in system
    assert "untrusted" in system


def test_quote_validation_against_cited_passage_with_pack_fallback() -> None:
    pack = make_pack()
    out = judge_output("supported", [
        ("P1", RESULT_TEXT, "supports"),
        ("P1", ABSTRACT.split(". ")[1], "closest"),  # really in A: wrong id, still found
        ("P1", "Drug X cured every patient instantly.", "supports"),  # fabricated
    ])
    validated, invalid = validate_output_quotes(out, pack)
    assert [q.role for q in validated] == ["supports", "closest"]
    assert invalid == ["Drug X cured every patient instantly."]


async def test_run_layer_success_records_metadata() -> None:
    ctx = make_ctx()
    out = judge_output("supported", [("P1", RESULT_TEXT, "supports")])
    fake = AsyncMock(return_value=llm_result(out))
    with patch(_PATCH, fake):
        result = await run_layer("verifier", ctx.pack, ctx.claim, ctx, "verify_claim",
                                 timeout=60)
    assert result.verdict == "supported" and result.axis == "positive"
    assert result.quotes("supports") and not result.invalid_quotes
    assert result.model_id == "gpt-6-luna" and result.cost_usd == pytest.approx(0.0002)
    kwargs = fake.await_args.kwargs if fake.await_args else {}
    assert kwargs["role"] == "verifier" and kwargs["system_template"] == "verify_claim"
    assert kwargs["system_variables"] == system_variables() and kwargs["timeout"] == 60


@pytest.mark.parametrize(("exc", "kind"), [
    (LLMCallError("down", "transient", "gpt-6-luna"), "transient"),
    (NoModelAvailableError("none left"), "unavailable"),
    (CostLimitExceededError("$50"), "budget"),
    (TimeoutError(), "timeout"),
])
async def test_run_layer_failures_never_raise(exc: Exception, kind: str) -> None:
    ctx = make_ctx()
    with patch(_PATCH, AsyncMock(side_effect=exc)):
        result = await run_layer("judge", ctx.pack, ctx.claim, ctx, "judge_claim")
    assert result.output is None and result.error_kind == kind and result.error


async def test_run_layer_skips_call_when_budget_exhausted() -> None:
    ctx = make_ctx()
    fake = AsyncMock()
    with patch(_PATCH, fake):
        result = await run_layer("judge", ctx.pack, ctx.claim, ctx, "judge_claim", timeout=0.5)
    fake.assert_not_awaited()
    assert result.error_kind == "timeout"


@pytest.mark.usefixtures("strict")
@pytest.mark.parametrize(("abstract", "kept"), [
    (None, []),  # title only: the model cannot know what the other reference states
    ("Gel Y restored limb function in rats.", ["cocited_share"]),
])
async def test_cocited_share_needs_a_co_cited_abstract(abstract: str | None,
                                                       kept: list[str]) -> None:
    ctx = make_ctx(make_claim(co_cited=2))
    ctx.co_cited = [co_cited_ref(7, "Gel Y in rats", abstract)]
    out = judge_output("supported", [("P1", RESULT_TEXT, "supports")]).model_copy(update={
        "benign_notes": ["cocited_share"], "dismissed": [Dismissal(
            element="restored limb function", guard="cocited_share", passage_id="7",
            quote="Gel Y restored limb function in rats.")]})
    with patch(_PATCH, AsyncMock(return_value=llm_result(out))):
        result = await run_layer("verifier", ctx.pack, ctx.claim, ctx, "verify_claim")
    assert result.output is not None and result.output.benign_notes == kept
    # A rejected clearance leaves its element uncovered: an unusual positive (cross-checked).
    assert uncovered_elements(result.output) == ([] if kept else ["restored limb function"])
    assert bool(result.rejected_dismissals) is not bool(kept)


@pytest.mark.usefixtures("strict")
async def test_benign_notes_without_a_dismissal_clear_nothing() -> None:
    ctx = make_ctx(make_claim(co_cited=2))
    ctx.co_cited = [co_cited_ref(7, "Gel Y in rats", "Gel Y restored limb function in rats.")]
    out = judge_output("supported", [("P1", RESULT_TEXT, "supports")]).model_copy(update={
        "benign_notes": ["cocited_share"], "unsupported_elements": ["restored limb function"]})
    with patch(_PATCH, AsyncMock(return_value=llm_result(out))):
        result = await run_layer("verifier", ctx.pack, ctx.claim, ctx, "verify_claim")
    assert result.output is not None and result.output.benign_notes == []
    assert uncovered_elements(result.output) == ["restored limb function"]
