"""REFCHECK_STRICT_CLEARANCE: V5.5 verifier behaviour by default, V5.6 strict when on.

The default must send byte-identical V5.5 requests (prompts, schema, output model
name) so the LLM cache reuses the V5.5 answers; strict mode keeps the V5.6 prompts,
schema and dismissal audit (tests/unit/test_verify_dismissals.py).
"""

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from refcheck.llm.schema import schema_name, strict_json_schema
from refcheck.llm.templates import render_template
from refcheck.models import verification_v55
from refcheck.models.verification import Dismissal, EvidenceQuote, JudgeOutput
from refcheck.stages.verify_claims.clearance_mode import (
    layer_output,
    request_model,
    strict_clearance,
    template_for,
)
from refcheck.stages.verify_claims.cocited import co_cited_ref
from refcheck.stages.verify_claims.layers import run_layer
from refcheck.stages.verify_claims.partial_fields import uncovered_elements
from refcheck.stages.verify_claims.taxonomy_prompt import system_variables
from tests.unit.verify_fakes import (
    RESULT_TEXT,
    judge_output,
    llm_result,
    make_claim,
    make_ctx,
    make_pack,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "eval"))

import eval_data  # noqa: E402
from eval_cli import parse_args  # noqa: E402
from eval_roles import apply_overrides  # noqa: E402

_PATCH = "refcheck.stages.verify_claims.layers.call_llm_raw"
# Recorded by the V5.5 gold runs (gold-v55b-union-haiku, gold-v55-final-test): a change to
# the default prompt files invalidates every cached V5.5 verifier / judge / confirm answer.
V55_HASHES = {"verify_claim": "8a9f32632e6d90a2", "judge_claim": "b8bd3166f9dcba35"}
_ELEMENT = "restored limb function"


@pytest.mark.parametrize(("value", "on"), [(None, False), ("off", False), ("on", True),
                                           ("1", True), ("bogus", False)])
def test_switch_defaults_off(monkeypatch: pytest.MonkeyPatch, value: str | None,
                             on: bool) -> None:
    if value is not None:
        monkeypatch.setenv("REFCHECK_STRICT_CLEARANCE", value)
    assert strict_clearance() is on


def test_prompt_files_per_mode() -> None:
    assert template_for("verify_claim", False) == "verify_claim"
    assert template_for("judge_claim", True) == "judge_claim_strict"
    assert template_for("verify_claim_strict", False) == "verify_claim"
    for name in ("verify_claim", "judge_claim"):
        default = render_template(name, system_variables())
        strict = render_template(name + "_strict", system_variables())
        assert "No quote, no clearance" not in default and '"dismissed"' not in default
        assert "No quote, no clearance" in strict and '"dismissed"' in strict


def test_default_prompt_files_are_the_v55_ones() -> None:
    hashes = eval_data.prompt_hashes()
    assert {k: hashes[k] for k in V55_HASHES} == V55_HASHES
    strict = eval_data.prompt_hashes(strict=True)
    assert all(strict[k] != v for k, v in V55_HASHES.items())


def test_schema_fields_per_mode() -> None:
    v55, v56 = request_model(False), request_model(True)
    assert v56 is JudgeOutput and v55 is verification_v55.JudgeOutput
    assert v55.__name__ == "JudgeOutput" and schema_name(v55) == schema_name(v56)
    old: Any = strict_json_schema(v55)
    new: Any = strict_json_schema(v56)
    assert "dismissed" in new["properties"] and "dismissed" not in old["properties"]
    # The V5.5 schema is the V5.6 one without "dismissed" and quote "states".
    del new["properties"]["dismissed"]
    new["required"].remove("dismissed")
    item = new["properties"]["quotes"]["items"]
    del item["properties"]["states"]
    item["required"].remove("states")
    assert old == new


def test_off_mode_output_drops_states_and_dismissals() -> None:
    quote = EvidenceQuote.model_validate({"passage_id": "P1", "text": RESULT_TEXT,
                                          "role": "supports", "states": ""})
    out = judge_output("supported").model_copy(update={"quotes": [quote], "dismissed": [
        Dismissal(element="x", guard="overliteral_wording", passage_id="P1", quote="y")]})
    off = layer_output(out, strict=False)
    assert off.dismissed == [] and "states" not in off.quotes[0].model_fields_set
    assert layer_output(out, strict=True) is out


def _shared_out() -> JudgeOutput:
    return judge_output("supported", [("P1", RESULT_TEXT, "supports")]).model_copy(update={
        "benign_notes": ["cocited_share"], "unsupported_elements": [_ELEMENT]})


async def test_default_request_is_v55_and_notes_clear_elements() -> None:
    ctx = make_ctx(make_claim(co_cited=2))
    ctx.co_cited = [co_cited_ref(7, "Gel Y in rats", "Gel Y restored limb function in rats.")]
    fake = AsyncMock(return_value=llm_result(_shared_out()))
    with patch(_PATCH, fake):
        result = await run_layer("confirm", ctx.pack, ctx.claim, ctx, "verify_claim")
    assert fake.await_args is not None
    assert fake.await_args.args[0] == "verify_claim"
    assert fake.await_args.args[2] is verification_v55.JudgeOutput
    assert fake.await_args.kwargs["system_template"] == "verify_claim"
    assert result.output is not None and result.output.benign_notes == ["cocited_share"]
    assert uncovered_elements(result.output) == [] and result.rejected_dismissals == []


async def test_default_drops_cocited_share_without_a_co_cited_abstract() -> None:
    ctx = make_ctx(make_claim(co_cited=2))
    ctx.co_cited = [co_cited_ref(7, "Gel Y in rats", None)]  # title only
    with patch(_PATCH, AsyncMock(return_value=llm_result(_shared_out()))):
        result = await run_layer("verifier", ctx.pack, ctx.claim, ctx, "verify_claim")
    assert result.output is not None and result.output.benign_notes == []
    assert uncovered_elements(result.output) == [_ELEMENT]


@pytest.mark.usefixtures("strict")
async def test_strict_request_uses_the_v56_prompt_and_schema() -> None:
    ctx = make_ctx()
    fake = AsyncMock(return_value=llm_result(_shared_out()))
    with patch(_PATCH, fake):
        result = await run_layer("judge", ctx.pack, ctx.claim, ctx, "judge_claim")
    assert fake.await_args is not None
    assert fake.await_args.args[0] == "judge_claim_strict"
    assert fake.await_args.args[2] is JudgeOutput
    assert result.output is not None and result.output.benign_notes == []  # no dismissal


async def test_default_keeps_front_matter_out_of_evidence() -> None:
    title = "Drug X in mice"  # make_ref's title
    ctx = make_ctx(pack=make_pack(texts=(f"{title}. {RESULT_TEXT}",)))
    out = judge_output("supported", [("P1", title, "supports"), ("P1", RESULT_TEXT, "supports"),
                                     ("P1", RESULT_TEXT[:40], "supports")])
    with patch(_PATCH, AsyncMock(return_value=llm_result(out))):
        result = await run_layer("verifier", ctx.pack, ctx.claim, ctx, "verify_claim")
    assert [q.text for q in result.validated_quotes] == [RESULT_TEXT]  # title + contained dup
    assert [q.text for q in result.context_quotes] == [title]


@pytest.mark.parametrize(("flag", "env"), [(["--strict-clearance", "on"], "on"),
                                           (["--strict-clearance", "off"], "off")])
def test_eval_flag_sets_the_switch(monkeypatch: pytest.MonkeyPatch, flag: list[str],
                                   env: str) -> None:
    monkeypatch.setenv("REFCHECK_STRICT_CLEARANCE", "")  # restored after the test
    cfg = parse_args(["--dataset", "smoke", *flag])
    assert cfg.strict_clearance == env
    apply_overrides(cfg)
    assert strict_clearance() is (env == "on")
