"""V5.7 element-check changes through the real cascade (scripted layers, no network):
#2 slot audit, #13 co-cited-only clearance, #11 survivor types, #6 credit rubric."""

import pytest

from refcheck.stages.verify_claims.slot_apply import SLOT_LAYER
from refcheck.stages.verify_claims.slot_audit import slot_phrases
from tests.unit.adjudicate_cascade import assert_coherent, haiku, route
from tests.unit.adjudicate_fakes import (
    ABSENT,
    BROADENED,
    COCITED,
    OVERSTATED,
    STATED,
    WORDING,
    answer_all,
    ctx_with_cocited,
    enable,
    with_elements,
)
from tests.unit.verify_fakes import FULL_TEXT, make_claim, make_ctx

SLOT_CLAIM = "Drug X reduces inflammation in mice every year."


@pytest.fixture(autouse=True)
def _on(monkeypatch: pytest.MonkeyPatch) -> None:
    enable(monkeypatch)


def _supported() -> dict[str, list]:  # type: ignore[type-arg]
    return {"verifier": [haiku("supported")]}


def test_slot_phrases_absent_from_source_and_lexicon() -> None:
    found = slot_phrases(SLOT_CLAIM, FULL_TEXT, [])
    assert [(s.slot, s.phrase, s.partial_type) for s in found] == [
        ("time frame", "every year", "specific_detail_mismatch")]
    assert found[0].element == "time frame: 'every year'"
    assert not slot_phrases(SLOT_CLAIM, FULL_TEXT + " Ten mice per year.", [])  # lexicon
    assert not slot_phrases("Drug X is used widely in all mice.", FULL_TEXT, [])  # quantifiers
    source = "Drug X lowered IL-6 in mice."
    assert [s.slot for s in slot_phrases("It must be used in pigs.", source, [])] == [
        "recommendation", "population"]
    assert [s.slot for s in slot_phrases("It must be used in pigs.", FULL_TEXT, [])] == [
        "population"]  # "Further work is needed": a need-group synonym
    assert not slot_phrases("It must be used in pigs.", source, ["needed in swine"])


async def test_a_surviving_slot_makes_supported_a_minor_partial() -> None:
    calls: list[dict[str, object]] = []
    ctx = make_ctx(make_claim(SLOT_CLAIM))
    _, result = await route(ctx, _supported(), answer_all(ABSENT), calls)
    assert [c["variables"]["elements"] for c in calls] == [  # type: ignore[index]
        ["time frame: 'every year'"]]
    assert result.verdict == "partially_supported" and result.needs_user_review
    assert (result.partial_type, result.partial_severity) == ("specific_detail_mismatch",
                                                              "minor")
    assert result.unsupported_elements == ["time frame: 'every year'"]
    assert "Slot check: the cited text adds a time frame ('every year')" in result.reasoning
    assert result.layer_path[-1] == SLOT_LAYER and result.consensus_type == "adjudicated"
    assert_coherent(result)


async def test_a_cleared_slot_keeps_supported_and_the_trace() -> None:
    ctx = make_ctx(make_claim(SLOT_CLAIM))
    _, result = await route(ctx, _supported(), answer_all(STATED))
    assert result.verdict == "supported" and result.layer_path[-1] == SLOT_LAYER
    assert result.model_reasoning[-1].verdict == "supported"
    assert_coherent(result)


@pytest.mark.parametrize("setting", ["disabled", "abstract", "no_slot"])
async def test_no_slot_call(monkeypatch: pytest.MonkeyPatch, setting: str) -> None:
    calls: list[dict[str, object]] = []
    if setting == "disabled":
        monkeypatch.setenv("REFCHECK_V57_DISABLE", "2")
    claim = make_claim("Drug X reduces inflammation in mice." if setting == "no_slot"
                       else SLOT_CLAIM)
    ctx = make_ctx(claim, coverage="abstract_only" if setting == "abstract" else "full_text")
    _, result = await route(ctx, _supported(), answer_all(ABSENT), calls)
    assert not calls and result.verdict == "supported"
    assert SLOT_LAYER not in result.layer_path


def _partial(*elements: str, ptype: str = "missing_element") -> dict[str, list]:  # type: ignore[type-arg]
    return {"verifier": [with_elements(haiku("partially_supported"), *elements, ptype=ptype,
                                       severity="major" if ptype != "missing_element"
                                       else "minor")]}


async def test_cocited_only_clearance_is_a_tangential_citation() -> None:
    out, result = await route(ctx_with_cocited(), _partial("macrophages", "is solved"),
                              answer_all(COCITED, BROADENED))
    assert result.verdict == "not_supported" and result.needs_user_review
    assert result.partial_type == "tangential_source"
    assert "looks misplaced (tangential source)" in result.reasoning
    assert out.adjudication is not None and out.adjudication.outcome == "tangential"
    assert_coherent(result)


@pytest.mark.parametrize("answers", [(COCITED, ABSENT), (COCITED, STATED, BROADENED),
                                     (WORDING, BROADENED)])
async def test_any_own_statement_or_absent_survivor_stays_partial(answers: tuple) -> None:  # type: ignore[type-arg]
    elements = ("macrophages", "IL-6 reduction", "is solved")[:len(answers)]
    _, result = await route(ctx_with_cocited(), _partial(*elements), answer_all(*answers))
    assert result.verdict == "partially_supported"


async def test_cocited_only_rule_is_switchable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFCHECK_V57_DISABLE", "13")
    _, result = await route(ctx_with_cocited(), _partial("macrophages", "is solved"),
                            answer_all(COCITED, BROADENED))
    assert result.verdict == "partially_supported"


async def test_unchanged_outcome_is_typed_from_its_survivors() -> None:
    _, result = await route(ctx_with_cocited(), _partial("in all patients", "anti-IL-6"),
                            answer_all(BROADENED, ABSENT))
    assert (result.partial_type, result.partial_severity) == ("scope_overgeneralized", "major")
    assert result.unsupported_elements == ["in all patients", "anti-IL-6"]  # unchanged


async def test_unchanged_typing_is_switchable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFCHECK_V57_DISABLE", "11")
    _, result = await route(ctx_with_cocited(), _partial("in all patients", "anti-IL-6"),
                            answer_all(BROADENED, ABSENT))
    assert result.partial_type == "missing_element"


@pytest.mark.parametrize(("coverage", "ptype"), [("abstract_only", "coverage_limited"),
                                                 ("full_text", "unsupported_inference")])
async def test_all_absent_survivors_on_an_abstract_are_coverage_limited(
        coverage: str, ptype: str) -> None:
    # a relational element: V5.8 #26 types an all-noun-phrase list as missing_element
    _, result = await route(ctx_with_cocited(coverage), _partial(
        "the benefit is inferred from x", "x", ptype="unsupported_inference"),
        answer_all(ABSENT, ABSENT))
    assert result.partial_type == ptype


async def test_overstated_alone_is_unchanged_without_a_credit_panel() -> None:
    _, result = await route(ctx_with_cocited(), _partial("definite elimination"),
                            answer_all(OVERSTATED))
    assert result.verdict == "partially_supported"
    assert result.partial_type == "certainty_overstated"
