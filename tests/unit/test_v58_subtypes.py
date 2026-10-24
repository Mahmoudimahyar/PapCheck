"""V5.8 deterministic sub-type corrections (subtype_rules.py; synthetic data, no network).

Adjudicator side through the real cascade: own share unsupported -> tangential_source,
exclusive terms -> certainty_overstated, an unwitnessed cross-check specific ->
missing_element. Shown-result side on partial_fields: a routed verifier's tangential
type kept on a cross-check partial, a narrower subject on a softened "not relevant" ->
scope, an untyped re-check inherits the first run's type. All off with
REFCHECK_V57_DISABLE=11.
"""

import pytest

from refcheck.stages.verify_claims.layers import LayerResult
from refcheck.stages.verify_claims.partial_fields import partial_fields
from tests.unit.adjudicate_cascade import assert_coherent, haiku, luna, route
from tests.unit.adjudicate_fakes import (
    ABSENT,
    BROADENED,
    COCITED,
    CONTRADICTED,
    STATED,
    Answer,
    answer_all,
    ctx_with_cocited,
    enable,
    with_elements,
)
from tests.unit.verify_fakes import layer

SHARED, ABSENT_PART = "in skin wounds", "lowers IL-6"  # the co-cited abstract states SHARED


@pytest.fixture(autouse=True)
def _on(monkeypatch: pytest.MonkeyPatch) -> None:
    enable(monkeypatch)


def _dispute(*elements: str, ptype: str = "specific_detail_mismatch",
             verifier_type: str = "missing_element") -> dict[str, list[LayerResult]]:
    """Verifier not_supported (closest quotes only); the cross-check finds a partial."""
    verifier = with_elements(haiku("not_supported", role_quote="closest"), *elements,
                             ptype=verifier_type, severity="major")
    confirm = with_elements(luna("partially_supported"), *elements, ptype=ptype,
                            severity="major")
    return {"verifier": [verifier], "confirm": [confirm]}


async def _shown(script: dict[str, list[LayerResult]], *answers: Answer,
                 coverage: str = "full_text") -> tuple[str, str | None, str | None]:
    _, result = await route(ctx_with_cocited(coverage), script, answer_all(*answers))
    assert_coherent(result)
    return result.verdict, result.partial_type, result.partial_severity


async def test_own_share_unsupported_is_a_tangential_partial() -> None:
    shown = await _shown(_dispute(SHARED, ABSENT_PART), COCITED, ABSENT)
    assert shown == ("partially_supported", "tangential_source", "major")


async def test_tangential_share_rule_is_switchable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFCHECK_V57_DISABLE", "11")
    shown = await _shown(_dispute(SHARED, ABSENT_PART), COCITED, ABSENT)
    assert shown[1] == "specific_detail_mismatch"  # the cross-check's type, as in V5.7


@pytest.mark.parametrize("answers", [(COCITED, CONTRADICTED), (STATED, ABSENT)])
async def test_a_different_specific_or_an_own_statement_is_not_tangential(
        answers: tuple[Answer, Answer]) -> None:
    shown = await _shown(_dispute(SHARED, ABSENT_PART), *answers)
    assert shown[0] == "partially_supported" and shown[1] != "tangential_source"


async def test_a_broadened_survivor_stays_with_the_cocited_only_rule() -> None:
    shown = await _shown(_dispute(SHARED, ABSENT_PART), COCITED, BROADENED)
    assert shown[:2] == ("not_supported", "tangential_source")  # V5.7 #13, not this rule


async def test_tangential_share_needs_a_full_text_and_a_cross_check_reading() -> None:
    abstract = await _shown(_dispute(SHARED, ABSENT_PART), COCITED, ABSENT,
                            coverage="abstract_only")
    assert abstract[1] != "tangential_source"
    own = {"verifier": [with_elements(haiku("partially_supported"), SHARED, ABSENT_PART)]}
    assert (await _shown(own, COCITED, ABSENT))[1] == "missing_element"


@pytest.mark.parametrize(("elements", "expected"), [
    (("gel chemistry alone", "the sole cause of tolerance"), ("certainty_overstated", "minor")),
    (("a 40% reduction",), ("specific_detail_mismatch", "major")),
])
async def test_contradicted_exclusive_terms_are_certainty_overstated(
        elements: tuple[str, ...], expected: tuple[str, str]) -> None:
    verifier = with_elements(haiku("partially_supported"), *elements,
                             ptype="unsupported_inference", severity="major")
    shown = await _shown({"verifier": [verifier]}, *[CONTRADICTED] * len(elements))
    assert shown[1:] == expected


@pytest.mark.parametrize(("element", "expected"), [
    ("tuned degradation profiles", "missing_element"),
    ("hypertension in 71% by 1 year", "specific_detail_mismatch"),
])
async def test_an_unwitnessed_cross_check_specific_becomes_missing_element(
        element: str, expected: str) -> None:
    shown = await _shown(_dispute(element), ABSENT)
    assert shown[1] == expected


def _typed(lay: LayerResult, ptype: str, problem: str = "none") -> LayerResult:
    assert lay.output is not None
    out = lay.output.model_copy(update={"partial_type": ptype, "problem_type": problem,
                                        "unsupported_elements": ["an element"]})
    return lay.model_copy(update={"output": out})


def _verifier(verdict: str, ptype: str, name: str = "verifier",
              problem: str = "none") -> LayerResult:
    return _typed(layer(name, verdict, role_quote="closest", severity="major"), ptype, problem)


def _confirm(verdict: str, ptype: str) -> LayerResult:
    return _typed(layer("confirm", verdict, severity="major"), ptype)


def test_a_cross_check_partial_keeps_the_verifiers_tangential_type() -> None:
    confirm = _confirm("partially_supported", "specific_detail_mismatch")
    layers = [_verifier("not_supported", "tangential_source"), confirm]
    found = partial_fields("partially_supported", confirm, layers, "full_text", [])
    assert (found.partial_type, found.partial_severity) == ("tangential_source", "major")
    layers = [_verifier("not_supported", "missing_element"), confirm]
    found = partial_fields("partially_supported", confirm, layers, "full_text", [])
    assert found.partial_type == "specific_detail_mismatch"


def test_a_softened_not_relevant_with_a_narrower_subject_is_scope() -> None:
    verifier = _verifier("not_relevant", "tangential_source")
    layers = [verifier, _confirm("partially_supported", "scope_overgeneralized")]
    found = partial_fields("not_supported", verifier, layers, "full_text", [])
    assert found.partial_type == "scope_overgeneralized"
    layers = [verifier, _confirm("partially_supported", "missing_element")]
    found = partial_fields("not_supported", verifier, layers, "full_text", [])
    assert found.partial_type == "tangential_source"


def test_an_untyped_recheck_inherits_the_first_runs_type() -> None:
    second = _verifier("contradicted", "none", "verifier_recheck", problem="wrong_direction")
    layers = [_verifier("partially_supported", "unsupported_inference"), second]
    found = partial_fields("contradicted", second, layers, "full_text", [])
    assert (found.partial_type, found.partial_severity) == ("unsupported_inference", "major")
    assert partial_fields("contradicted", second, [second], "full_text",
                          []).partial_type == "specific_detail_mismatch"  # legacy mapping


def test_shown_result_rules_are_switchable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFCHECK_V57_DISABLE", "11")
    confirm = _confirm("partially_supported", "specific_detail_mismatch")
    layers = [_verifier("not_supported", "tangential_source"), confirm]
    found = partial_fields("partially_supported", confirm, layers, "full_text", [])
    assert found.partial_type == "specific_detail_mismatch"
