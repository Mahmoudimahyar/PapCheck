"""Element adjudicator: survivors' type, failures, abstract-only, switch, once per pair."""

import time

import pytest

from refcheck.llm import CostTracker
from refcheck.llm.errors import LLMRefusalError
from refcheck.stages.verify_claims.adjudicate_apply import adjudicate_outcome
from refcheck.stages.verify_claims.layers import LayerResult
from tests.unit.adjudicate_cascade import assert_coherent, haiku, route
from tests.unit.adjudicate_fakes import (
    ABSENT,
    BROADENED,
    CONTRADICTED,
    FRAMING,
    OVERSTATED,
    STATED,
    WORDING,
    Answer,
    answer_all,
    ctx_with_cocited,
    enable,
    fake_call,
    with_elements,
)

# E2 carries no quantifier: V5.8 #26 types a survivor "in all patients" as scope (b).
E1, E2, E3 = "anti-inflammatory effect", "in treated patients", "for 60 days"
MISSING, SCOPE = ("missing_element", "minor"), ("scope_overgeneralized", "major")


def _partial(*elements: str, ptype: str = "missing_element",
             severity: str = "minor") -> dict[str, list[LayerResult]]:
    return {"verifier": [with_elements(haiku("partially_supported"), *elements, ptype=ptype,
                                       severity=severity)]}


@pytest.mark.parametrize(("answers", "routed", "ptype", "severity"), [
    ((WORDING, OVERSTATED, OVERSTATED), MISSING, "certainty_overstated", "minor"),
    ((WORDING, ABSENT, CONTRADICTED), MISSING, "specific_detail_mismatch", "major"),
    # V5.7 #11: an absent survivor no longer vetoes the others' type
    ((WORDING, ABSENT, OVERSTATED), MISSING, "certainty_overstated", "minor"),
    ((WORDING, BROADENED, OVERSTATED), MISSING, "scope_overgeneralized", "major"),
    # never downgraded: the routed type outranks what the survivors imply
    ((FRAMING, OVERSTATED, OVERSTATED), SCOPE, "scope_overgeneralized", "major"),
    ((WORDING, OVERSTATED, BROADENED), ("unsupported_inference", "major"),
     "unsupported_inference", "major"),
    ((WORDING, CONTRADICTED, OVERSTATED), SCOPE, "specific_detail_mismatch", "major"),
])
async def test_survivors_decide_the_partial_type(monkeypatch: pytest.MonkeyPatch,
                                                 answers: tuple[Answer, ...],
                                                 routed: tuple[str, str], ptype: str,
                                                 severity: str) -> None:
    enable(monkeypatch)
    _, result = await route(ctx_with_cocited(), _partial(E1, E2, E3, ptype=routed[0],
                                                         severity=routed[1]),
                            answer_all(*answers))
    assert result.verdict == "partially_supported"
    assert result.unsupported_elements == [E2, E3]
    assert (result.partial_type, result.partial_severity) == (ptype, severity)
    assert f"'{E2}'" in result.author_action
    assert_coherent(result)


async def test_fabricated_quote_changes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    enable(monkeypatch)
    monkeypatch.setenv("REFCHECK_ADJUDICATE", "off")
    _, before = await route(ctx_with_cocited(), _partial(E1), answer_all(WORDING))
    enable(monkeypatch)
    fabricated = ("stated", "P1", "Drug X cured every single patient in the trial", "")
    out, after = await route(ctx_with_cocited(), _partial(E1), answer_all(fabricated))
    assert out.adjudication is not None and out.adjudication.outcome == "unchanged"
    for field in ("verdict", "partial_type", "partial_severity", "author_action",
                  "unsupported_elements", "guards_applied", "needs_user_review",
                  "consensus_type", "reasoning"):
        assert getattr(after, field) == getattr(before, field), field
    assert after.layer_path == [*before.layer_path, "adjudicate"]
    assert after.model_reasoning[-1].verdict == "partially_supported"
    assert_coherent(after)


@pytest.mark.parametrize("error", [LLMRefusalError("refused", "claude-haiku-5-5"),
                                   TimeoutError("slow")])
async def test_failed_call_leaves_the_verdict(monkeypatch: pytest.MonkeyPatch,
                                              error: Exception) -> None:
    enable(monkeypatch)
    out, result = await route(ctx_with_cocited(), _partial(E1), lambda elements: error)
    assert result.verdict == "partially_supported" and result.unsupported_elements == [E1]
    assert out.adjudication is not None and out.adjudication.outcome == "error"
    assert result.model_reasoning[-1].verdict == "error"
    assert result.consensus_type == "verifier"
    assert_coherent(result)


async def test_abstract_only_keeps_absent_elements_as_coverage_limited(
        monkeypatch: pytest.MonkeyPatch) -> None:
    enable(monkeypatch)
    _, result = await route(ctx_with_cocited("abstract_only"), _partial(E1, E2),
                            answer_all(WORDING, ABSENT))
    assert result.verdict == "partially_supported" and result.unsupported_elements == [E2]
    assert result.partial_type == "coverage_limited"
    abstract_quote = ("stated", "A", "drug X reduced inflammation markers in treated mice", "")
    _, cleared = await route(ctx_with_cocited("abstract_only"), _partial(E1, E2),
                             answer_all(WORDING, abstract_quote))
    assert cleared.verdict == "supported"
    assert cleared.evidence_quotes and "inflammation markers" in " ".join(cleared.evidence_quotes)
    assert_coherent(result)
    assert_coherent(cleared)


async def test_switch_off_never_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []
    out, result = await route(ctx_with_cocited(), _partial(E1), answer_all(WORDING), calls)
    assert not calls and out.adjudication is None and result.verdict == "partially_supported"


async def test_runs_at_most_once_and_respects_the_budget(
        monkeypatch: pytest.MonkeyPatch) -> None:
    enable(monkeypatch)
    calls: list[dict[str, object]] = []
    out, _ = await route(ctx_with_cocited(), _partial(E1, E2), answer_all(WORDING, ABSENT),
                         calls)
    assert out.verdict == "partially_supported" and len(calls) == 1
    with fake_call(answer_all(WORDING), calls):
        again = await adjudicate_outcome(ctx_with_cocited(), out, None, time.monotonic() + 100)
    assert again is out and len(calls) == 1
    _, spent = await route(ctx_with_cocited(), _partial(E1), answer_all(STATED), calls,
                           tracker=CostTracker(max_cost=0.0))
    assert len(calls) == 1 and spent.verdict == "partially_supported"
    assert spent.model_reasoning[-1].verdict == "error"
