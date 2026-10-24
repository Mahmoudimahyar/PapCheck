"""V5.7 #1 (re-check closure) and #11 (re-check keeps the first type): synthetic, no network."""

import pytest

from refcheck.stages.verify_claims.layers import LayerResult, ValidatedQuote
from refcheck.stages.verify_claims.recheck_closure import (
    closure_needed,
    keep_first_type,
    same_elements,
)
from tests.unit.adjudicate_cascade import assert_coherent, haiku, luna, recheck_layer, route
from tests.unit.adjudicate_fakes import (
    ABSENT,
    FABRICATED,
    STATED,
    answer_all,
    ctx_with_cocited,
    enable,
    with_elements,
)
from tests.unit.verify_fakes import RESULT_TEXT

E1, E2 = "hydrogels in general mimic native tissue", "lowers IL-6"


@pytest.fixture(autouse=True)
def _on(monkeypatch: pytest.MonkeyPatch) -> None:
    enable(monkeypatch)


def closest_only(verdict: str, *elements: str) -> LayerResult:
    """A first run whose only quotes are 'closest' (no validated supports quote)."""
    return with_elements(haiku(verdict, role_quote="closest"), *elements)


def test_closure_needed_only_for_upgrades_not_backed_by_a_first_supports_quote() -> None:
    supported = recheck_layer("supported")
    assert closure_needed(closest_only("partially_supported", E1), supported)
    assert closure_needed(closest_only("not_supported", E1), supported)
    assert not closure_needed(with_elements(haiku("partially_supported"), E1), supported)
    assert not closure_needed(closest_only("partially_supported", E1),
                              recheck_layer("partially_supported"))
    assert not closure_needed(closest_only("partially_supported"), supported)  # no elements
    first = closest_only("partially_supported", E1)
    assert not closure_needed(first, first)  # the re-check did not run


async def test_flip_without_first_supports_quote_goes_to_the_adjudicator() -> None:
    first = closest_only("partially_supported", E1, E2)
    calls: list[dict[str, object]] = []
    out, result = await route(ctx_with_cocited(), {
        "verifier": [first], "verifier_recheck": [recheck_layer("supported")]},
        answer_all(STATED, ABSENT), calls)
    assert calls[-1]["variables"]["elements"] == [E1, E2]  # type: ignore[index]
    assert calls[-1]["variables"]["pack_kind"] == "recheck"  # type: ignore[index]
    assert result.verdict == "partially_supported" and result.unsupported_elements == [E2]
    assert result.layer_path == ["verifier", "verifier_recheck", "adjudicate"]
    assert any("first check gave no supporting quote" in n for n in out.notes)
    assert_coherent(result)


async def test_flip_closed_with_exact_quotes_is_supported() -> None:
    first = closest_only("partially_supported", E1, E2)
    out, result = await route(ctx_with_cocited(), {
        "verifier": [first], "verifier_recheck": [recheck_layer("supported")]},
        answer_all(STATED, STATED))
    assert result.verdict == "supported" and out.adjudication is not None
    assert out.adjudication.outcome == "cleared"
    assert_coherent(result)


async def test_fabricated_clearing_quote_keeps_the_closure_partial() -> None:
    first = closest_only("partially_supported", E1)
    _, result = await route(ctx_with_cocited(), {
        "verifier": [first], "verifier_recheck": [recheck_layer("supported")]},
        answer_all(FABRICATED))
    assert result.verdict == "partially_supported" and result.unsupported_elements == [E1]
    assert_coherent(result)


async def test_flip_with_first_supports_quote_stays_final() -> None:
    first = with_elements(haiku("partially_supported"), E1)
    calls: list[dict[str, object]] = []
    _, result = await route(ctx_with_cocited(), {
        "verifier": [first], "verifier_recheck": [recheck_layer("supported")]},
        answer_all(ABSENT), calls)
    assert result.verdict == "supported" and calls == []


async def test_overturned_negative_needs_the_adjudicator_not_just_the_cross_check() -> None:
    first = closest_only("not_supported", E1)
    second = recheck_layer("supported").model_copy(update={"validated_quotes": [
        ValidatedQuote(passage_id="P1", text=RESULT_TEXT, role="closest", similarity=1.0)]})
    out, result = await route(ctx_with_cocited(), {
        "verifier": [first], "verifier_recheck": [second], "confirm": [luna("supported")]},
        answer_all(ABSENT))
    assert result.layer_path == ["verifier", "verifier_recheck", "confirm", "adjudicate"]
    assert result.verdict == "partially_supported" and result.unsupported_elements == [E1]
    assert result.needs_user_review
    assert any("first check said not_supported" in n for n in out.notes)
    assert_coherent(result)


async def test_closure_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFCHECK_V57_DISABLE", "3,1")
    first = closest_only("partially_supported", E1)
    calls: list[dict[str, object]] = []
    _, result = await route(ctx_with_cocited(), {
        "verifier": [first], "verifier_recheck": [recheck_layer("supported")]},
        answer_all(ABSENT), calls)
    assert result.verdict == "supported" and calls == []


def test_same_elements_allows_rewording() -> None:
    assert same_elements(["lowers IL-6 levels"], ["IL-6 levels lowers"])
    assert not same_elements([E1, E2], [E2])


def _typed(lay: LayerResult, ptype: str, *elements: str) -> LayerResult:
    return with_elements(lay, *elements, ptype=ptype, severity="major")


def test_same_element_rerun_keeps_the_first_type() -> None:
    first = _typed(haiku("partially_supported"), "scope_overgeneralized", E1)
    second = with_elements(recheck_layer("partially_supported"), E1,
                           ptype="certainty_overstated", severity="minor")
    kept = keep_first_type(first, second)
    assert kept.output is not None and second.output is not None
    assert (kept.output.partial_type, kept.output.severity) == ("scope_overgeneralized", "major")
    assert second.output.partial_type == "certainty_overstated"  # the trace is untouched
    assert kept.validated_quotes == second.validated_quotes


def test_changed_survivors_or_switch_off_keep_the_rerun_type(
        monkeypatch: pytest.MonkeyPatch) -> None:
    first = _typed(haiku("partially_supported"), "scope_overgeneralized", E1, E2)
    second = with_elements(recheck_layer("partially_supported"), E2,
                           ptype="certainty_overstated")
    assert keep_first_type(first, second) is second
    same = with_elements(recheck_layer("partially_supported"), E1, E2,
                         ptype="certainty_overstated")
    assert keep_first_type(first, same) is not same
    assert keep_first_type(first, recheck_layer("supported")).verdict == "supported"
    monkeypatch.setenv("REFCHECK_V57_DISABLE", "11")
    assert keep_first_type(first, same) is same


async def test_routed_partial_rerun_shows_the_first_type() -> None:
    first = _typed(haiku("partially_supported"), "scope_overgeneralized", E1)
    second = with_elements(recheck_layer("partially_supported"), E1,
                           ptype="certainty_overstated", severity="minor")
    out, result = await route(ctx_with_cocited(), {
        "verifier": [first], "verifier_recheck": [second]}, answer_all(ABSENT))
    assert result.verdict == "partially_supported"
    assert result.partial_type == "scope_overgeneralized"
    assert out.layers[1].output is not None
    assert out.layers[1].output.partial_type == "certainty_overstated"
    assert_coherent(result)
