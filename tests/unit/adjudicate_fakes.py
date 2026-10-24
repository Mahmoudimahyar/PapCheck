"""Builders for the element-adjudicator tests (synthetic texts, no network)."""

from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from unittest.mock import patch

import pytest

from refcheck.llm.structured import LLMCallResult
from refcheck.llm.usage import TokenUsage
from refcheck.models.adjudication import AdjudicateOutput, ElementCheck
from refcheck.stages.verify_claims.cocited import CoCitedRef
from refcheck.stages.verify_claims.layers import LayerResult
from refcheck.stages.verify_claims.verifier_helpers import PairContext
from tests.unit.verify_fakes import make_ctx

STATED_QUOTE = "Drug X reduced IL-6 levels by 40% compared with vehicle"  # in passage P1
COCITED_ABSTRACT = ("Gel Q lowered macrophage counts in rat skin wounds over two weeks "
                    "and was well tolerated.")
COCITED_QUOTE = "Gel Q lowered macrophage counts in rat skin wounds"
WORDING_QUOTE = "drug X is anti-inflammatory in mice"  # in the abstract (passage A)
CALL_PATH = "refcheck.stages.verify_claims.adjudicate.call_llm_raw"
Answer = tuple[str, str | None, str | None, str]  # category, passage_id, quote, note


def enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFCHECK_ADJUDICATE", "on")


def ctx_with_cocited(coverage: str = "full_text") -> PairContext:
    ctx = make_ctx(coverage=coverage)
    ctx.use_embeddings = False
    ctx.co_cited = [CoCitedRef(number=2, title="Gel Q in wounds", abstract=COCITED_ABSTRACT),
                    CoCitedRef(number=3, title="Drug X lowers IL-6 everywhere")]
    return ctx


def with_elements(lay: LayerResult, *elements: str, ptype: str = "missing_element",
                  severity: str = "minor") -> LayerResult:
    assert lay.output is not None
    out = lay.output.model_copy(update={"unsupported_elements": list(elements),
                                        "partial_type": ptype, "severity": severity,
                                        "problem_type": "compound_part_only"})
    return lay.model_copy(update={"output": out})


def output(elements: Sequence[str], answers: Sequence[Answer]) -> AdjudicateOutput:
    return AdjudicateOutput(
        elements=[ElementCheck(element=e, category=a[0], passage_id=a[1], quote=a[2],  # type: ignore[arg-type]
                               note=a[3]) for e, a in zip(elements, answers, strict=True)],
        explanation="Synthetic adjudication.")


def call_result(parsed: AdjudicateOutput) -> LLMCallResult[AdjudicateOutput]:
    return LLMCallResult[AdjudicateOutput](
        content=parsed.model_dump_json(), parsed=parsed, model_id="claude-haiku-5-5",
        litellm_id="anthropic/claude-haiku-5-5", provider="anthropic",
        display_name="claude-haiku-5-5", usage=TokenUsage(input_tokens=900, output_tokens=80),
        latency_ms=40, cost_usd=0.0001)


Responder = Callable[[list[str]], AdjudicateOutput | Exception]


def fake_call(respond: Responder, calls: list[dict[str, object]] | None = None,
              ) -> AbstractContextManager[object]:
    """Patch the adjudicator's call; ``respond`` gets the elements it was asked about."""
    async def fake(template: str, variables: dict[str, object], output_model: type,
                   **kwargs: object) -> LLMCallResult[AdjudicateOutput]:
        elements = [str(e) for e in variables["elements"]]  # type: ignore[attr-defined]
        if calls is not None:
            calls.append({"template": template, "variables": variables, **kwargs})
        answer = respond(elements)
        if isinstance(answer, Exception):
            raise answer
        return call_result(answer)

    return patch(CALL_PATH, fake)


def answer_all(*answers: Answer) -> Responder:
    """The same answers, in order, for whatever elements are asked."""
    return lambda elements: output(elements, list(answers)[:len(elements)])


WORDING: Answer = ("wording", "A", WORDING_QUOTE, "The source says 'anti-inflammatory'.")
# Framing quotes the passage stating the factual core it wraps (V5.6).
FRAMING: Answer = ("framing", "P1", STATED_QUOTE, "Enumeration added by the author.")
FRAMING_NO_QUOTE: Answer = ("framing", None, None, "Enumeration added by the author.")
STATED: Answer = ("stated", "P1", STATED_QUOTE, "P1 states it.")
FABRICATED: Answer = ("stated", "P1", "Drug X cured every patient within one single week", "")
COCITED: Answer = ("cocited", "2", COCITED_QUOTE, "Reference 2 reports it.")
ABSENT: Answer = ("absent", None, None, "Not in the passages.")
BROADENED: Answer = ("broadened", "P1", None, "The source studied mice only.")
OVERSTATED: Answer = ("overstated", "P1", None, "The source hedges.")
CONTRADICTED: Answer = ("contradicted", "P1", None, "The source gives another figure.")
