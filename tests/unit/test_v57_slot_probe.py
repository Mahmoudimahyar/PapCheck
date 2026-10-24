"""V5.7 #15: the blind slot probe on a flagged "supported" verdict (mocked LLM, synthetic text).

The probe sees the cited span with its relation / direction / population words masked;
a differing answer with an exact quote becomes ONE element-adjudicator element, and a
surviving element makes the pair partially_supported. Off unless REFCHECK_SLOT_PROBE=on.
"""

import time
from collections.abc import Callable
from typing import Any
from unittest.mock import patch

import pytest

from refcheck.llm import LLMError
from refcheck.llm.structured import LLMCallResult
from refcheck.llm.usage import TokenUsage
from refcheck.models.slot_probe import SlotAnswer, SlotProbeOutput
from refcheck.stages.verify_claims.calibration import ScreenThresholds
from refcheck.stages.verify_claims.cascade import CascadeOutcome
from refcheck.stages.verify_claims.cascade_helpers import build_result
from refcheck.stages.verify_claims.check_first import check_first_outcome
from refcheck.stages.verify_claims.slot_probe import PROBE_LAYER
from refcheck.stages.verify_claims.verifier_helpers import PairContext
from tests.unit.adjudicate_fakes import fake_call, output
from tests.unit.verify_fakes import layer, make_claim, make_ctx, screen

CLAIM = "Drug X increases inflammation in patients."
QUOTE = "drug X reduced inflammation markers in treated mice"  # in the abstract (passage A)
STATED = "Drug X reduced IL-6 levels by 40% compared with vehicle"  # in passage P1
PROBE_PATH = "refcheck.stages.verify_claims.slot_probe_call.call_llm_raw"
Answers = list[tuple[int, str, str | None, str | None]]


def _ctx() -> PairContext:
    ctx = make_ctx(make_claim(CLAIM))
    ctx.use_embeddings = False
    return ctx


def _supported() -> CascadeOutcome:
    lay = layer("verifier")
    return CascadeOutcome(verdict="supported", label_layer=lay, decided_by="verifier",
                          consensus_type="verifier", tier=2, layers=[lay],
                          layer_path=["screen", "verifier"])


def _probe(answers: Answers | Exception, calls: list[dict[str, Any]]) -> Any:
    async def fake(template: str, variables: dict[str, object], output_model: type,
                   **kwargs: object) -> LLMCallResult[SlotProbeOutput]:
        calls.append({"template": template, "variables": variables, **kwargs})
        if isinstance(answers, Exception):
            raise answers
        parsed = SlotProbeOutput(slots=[SlotAnswer(slot=n, answer=a, passage_id=p, quote=q)
                                        for n, a, p, q in answers], explanation="Probe.")
        return LLMCallResult[SlotProbeOutput](
            content=parsed.model_dump_json(), parsed=parsed, model_id="claude-haiku-5-5",
            litellm_id="anthropic/claude-haiku-5-5", provider="anthropic",
            display_name="claude-haiku-5-5", usage=TokenUsage(input_tokens=700, output_tokens=60),
            latency_ms=30, cost_usd=0.0003)
    return patch(PROBE_PATH, fake)


async def _run(monkeypatch: pytest.MonkeyPatch, answers: Answers | Exception,
               adjudicate: Callable[[list[str]], Any] | None = None,
               ) -> tuple[CascadeOutcome, list[dict[str, Any]], list[dict[str, object]]]:
    monkeypatch.setenv("REFCHECK_SLOT_PROBE", "on")
    monkeypatch.setenv("REFCHECK_ADJUDICATE", "on")
    monkeypatch.delenv("REFCHECK_V57_DISABLE", raising=False)
    probe_calls: list[dict[str, Any]] = []
    adj_calls: list[dict[str, object]] = []

    def no_adjudication(elements: list[str]) -> Any:
        raise AssertionError(f"no element check expected: {elements}")

    with _probe(answers, probe_calls), fake_call(adjudicate or no_adjudication, adj_calls):
        out = await check_first_outcome(_ctx(), screen(0.1), _supported(), None,
                                        time.monotonic() + 60)
    return out, probe_calls, adj_calls


async def test_the_probe_is_blind_and_a_differing_quoted_answer_survives(
        monkeypatch: pytest.MonkeyPatch) -> None:
    answers: Answers = [(1, "reduced", "A", QUOTE), (2, "treated mice", "A", QUOTE)]
    out, probe_calls, adj_calls = await _run(monkeypatch, answers, lambda elements: output(
        elements, [("contradicted", "A", QUOTE, "Reduced."), ("absent", None, None, "Mice.")]))
    variables = probe_calls[0]["variables"]
    assert variables["masked"] == "Drug X [SLOT 1] inflammation in [SLOT 2]."
    assert "increase" not in str(variables) and "patients" not in str(variables)
    assert probe_calls[0]["task"] == "verify_slot_probe" and probe_calls[0]["role"] == "adjudicator"
    assert adj_calls[0]["variables"]["elements"] == [  # type: ignore[index]
        "direction of effect: 'Drug X increases inflammation in patients'",
        "population: 'X increases inflammation in patients'"]
    assert out.verdict == "partially_supported" and out.needs_review
    assert out.layer_path[-1] == PROBE_LAYER and out.consensus_type == "adjudicated"
    label = out.label_layer
    assert label is not None and label.output is not None
    assert label.output.partial_type == "specific_detail_mismatch"
    assert label.output.severity == "major"
    assert label.cost_usd == pytest.approx(0.0004)  # probe + element check
    assert sum("Slot probe:" in n for n in out.notes) == 2
    assert not any(n.startswith("Check first:") for n in out.notes)  # no longer supported
    result = build_result(_ctx(), screen(0.1), out, ScreenThresholds(), 1)
    assert result.verdict == "partially_supported"
    assert result.partial_type == "specific_detail_mismatch"


async def test_an_absent_population_alone_is_a_minor_scope_partial(
        monkeypatch: pytest.MonkeyPatch) -> None:
    answers: Answers = [(1, "not stated", None, None), (2, "treated mice", "A", QUOTE)]
    out, _, adj_calls = await _run(monkeypatch, answers, lambda elements: output(
        elements, [("absent", None, None, "Only mice.")]))
    assert len(adj_calls) == 1 and out.verdict == "partially_supported"
    assert out.label_layer is not None and out.label_layer.output is not None
    assert out.label_layer.output.partial_type == "scope_overgeneralized"
    assert out.label_layer.output.severity == "minor"


async def test_a_cleared_element_keeps_the_verdict_and_records_the_layer(
        monkeypatch: pytest.MonkeyPatch) -> None:
    answers: Answers = [(2, "treated mice", "A", QUOTE)]
    out, _, adj_calls = await _run(monkeypatch, answers, lambda elements: output(
        elements, [("stated", "P1", STATED, "Stated.")]))
    assert len(adj_calls) == 1 and out.verdict == "supported" and out.needs_review
    assert out.layer_path[-2:] == ["verifier", PROBE_LAYER] and out.label_layer is not None
    assert out.label_layer.layer == "verifier" and out.layers[-1].cost_usd == pytest.approx(0.0004)
    assert out.notes[-1].startswith("Check first:")


@pytest.mark.parametrize("answers", [
    [(1, "increased", "A", QUOTE)],  # agrees with the claim
    [(1, "reduced", "A", "drug X reduced inflammation in every species")],  # not in the pack
    [(1, "reduced", "A", "reduced markers")],  # too short to count
    [(2, "not stated", None, None)],
])
async def test_no_element_without_a_differing_exact_answer(monkeypatch: pytest.MonkeyPatch,
                                                           answers: Answers) -> None:
    out, probe_calls, _ = await _run(monkeypatch, answers)
    assert len(probe_calls) == 1 and out.verdict == "supported"
    assert out.layer_path[-1] == PROBE_LAYER and out.layers[-1].output is not None


async def test_a_failed_probe_leaves_the_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    out, _, _ = await _run(monkeypatch, LLMError("boom", kind="transient"))
    assert out.verdict == "supported" and out.layers[-1].error is not None
    assert out.layers[-1].output is None and out.notes[-1].startswith("Check first:")


async def test_off_by_default_and_never_without_a_triage_reason(
        monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.delenv("REFCHECK_SLOT_PROBE", raising=False)
    with _probe([], calls):
        out = await check_first_outcome(_ctx(), screen(0.1), _supported(), None,
                                        time.monotonic() + 60)
    assert calls == [] and PROBE_LAYER not in out.layer_path
    monkeypatch.setenv("REFCHECK_SLOT_PROBE", "on")
    with _probe([], calls):
        out = await check_first_outcome(_ctx(), screen(0.9), _supported(), None,
                                        time.monotonic() + 60)
    assert calls == [] and out == _supported()
    monkeypatch.setenv("REFCHECK_ADJUDICATE", "off")
    with _probe([], calls):
        await check_first_outcome(_ctx(), screen(0.1), _supported(), None, time.monotonic() + 60)
    monkeypatch.setenv("REFCHECK_ADJUDICATE", "on")
    monkeypatch.setenv("REFCHECK_V57_DISABLE", "15")
    with _probe([], calls):
        await check_first_outcome(_ctx(), screen(0.1), _supported(), None, time.monotonic() + 60)
    assert calls == []


def test_the_prompt_renders_both_sections_without_the_claim() -> None:
    from refcheck.llm.templates import render_template

    system = render_template("slot_probe", {"section": "system"})
    assert "[SLOT 1]" in system and "VERBATIM" in system and "{{" not in system
    user = render_template("slot_probe", {
        "section": "user", "passages": "[P1] (Results, p.4) Drug X lowered IL-6.",
        "coverage": "full_text", "source_title": "Drug X in mice",
        "masked": "Drug X [SLOT 1] inflammation in [SLOT 2].",
        "slots": [{"number": 1, "kind": "direction"}, {"number": 2, "kind": "population"}]})
    assert "[SLOT 1]: the direction" in user and "[SLOT 2]: the population" in user
    assert "Drug X lowered IL-6." in user and "patients" not in user
