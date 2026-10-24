"""Element adjudicator on every cascade path that can show partially_supported.

Paths: verifier final, evidence re-check, cross-check confirmed, dispute
softening (not_supported vs supported), unusual positive (supported vs partial,
partial vs not_supported). Each path is checked for a coherent result (layer
trace, partial fields, guards, notes, review flag, consensus). A dispute is never
cleared to "supported", nor is a partial without a validated supports quote.
"""

import pytest

from refcheck.stages.verify_claims.layers import LayerResult
from tests.unit.adjudicate_cascade import assert_coherent, haiku, luna, recheck_layer, route
from tests.unit.adjudicate_fakes import (
    ABSENT,
    COCITED,
    FRAMING,
    STATED,
    WORDING,
    Answer,
    answer_all,
    ctx_with_cocited,
    enable,
    with_elements,
)

E1, E2, E3 = "two-stage scheme", "lowers IL-6", "in skin wounds"


@pytest.fixture(autouse=True)
def _on(monkeypatch: pytest.MonkeyPatch) -> None:
    enable(monkeypatch)


async def test_verifier_final_partial_fully_cleared_is_supported() -> None:
    verifier = with_elements(haiku("partially_supported"), E1, E2)
    out, result = await route(ctx_with_cocited(), {"verifier": [verifier]},
                              answer_all(FRAMING, STATED))
    assert (result.verdict, result.decided_by, result.consensus_type) == (
        "supported", "verifier", "adjudicated")
    assert not result.needs_user_review
    assert result.guards_applied == ["author_framing_or_example", "overliteral_wording"]
    assert f"Element check: '{E1}' - the author's framing" in result.reasoning
    assert result.layer_path == ["verifier", "adjudicate"]
    assert result.model_reasoning[-1].verdict == "supported"
    assert out.adjudication is not None and out.adjudication.outcome == "cleared"
    assert_coherent(result)


async def test_recheck_guard_is_kept_when_the_rest_is_cleared() -> None:
    first = with_elements(haiku("partially_supported"), E1, E2)
    second = with_elements(recheck_layer("partially_supported"), E2)
    _, result = await route(ctx_with_cocited(), {"verifier": [first],
                                                 "verifier_recheck": [second]},
                            answer_all(WORDING), recheck_cleared=[E1])
    assert result.verdict == "supported"
    assert result.guards_applied == ["evidence_recheck", "overliteral_wording"]
    assert result.layer_path == ["verifier", "verifier_recheck", "adjudicate"]
    assert_coherent(result)


async def test_confirmed_partial_partially_cleared_keeps_the_survivor() -> None:
    verifier = with_elements(haiku("partially_supported", supports=False), E1, E2)
    confirm = with_elements(luna("partially_supported"), E2)
    calls: list[dict[str, object]] = []
    out, result = await route(ctx_with_cocited(), {"verifier": [verifier], "confirm": [confirm]},
                              answer_all(ABSENT, ABSENT), calls)
    assert calls.pop()["variables"]["elements"] == [E2, E1]  # type: ignore[index]
    assert out.adjudication is not None and out.adjudication.outcome == "unchanged"
    verifier2 = with_elements(haiku("partially_supported", supports=False), E1, E2)
    confirm2 = with_elements(luna("partially_supported"), E1, E2)
    out, result = await route(ctx_with_cocited(), {"verifier": [verifier2],
                                                   "confirm": [confirm2]},
                              answer_all(FRAMING, ABSENT), calls)
    assert result.verdict == "partially_supported" and result.unsupported_elements == [E2]
    assert result.needs_user_review  # an unusual positive stays in the review queue
    assert result.consensus_type == "adjudicated"
    assert E2 in result.author_action and E1 not in result.author_action
    assert result.guards_applied == []
    assert f"Element check: '{E1}'" in result.reasoning
    assert_coherent(result)


def _dispute(*answers: Answer) -> dict[str, list[LayerResult]]:
    verifier = with_elements(haiku("not_supported", role_quote="closest"), E1, E3)
    return {"verifier": [verifier], "confirm": [luna("supported")]}


async def test_softened_dispute_is_never_cleared_to_supported() -> None:
    calls: list[dict[str, object]] = []
    out, result = await route(ctx_with_cocited(), _dispute(), answer_all(STATED, COCITED),
                              calls)
    asked = calls[0]["variables"]["elements"]  # type: ignore[index]
    assert asked == [E1, E3]
    assert out.adjudication is not None and out.adjudication.outcome == "held"
    assert (result.verdict, result.consensus_type) == ("partially_supported", "disputed")
    assert result.unsupported_elements == [E1, E3] and result.guards_applied == []
    assert result.needs_user_review and result.decided_by == "verifier"
    assert "stays partially supported because the two models disagreed" in result.reasoning
    assert f"Element check: '{E3}' - stated by a co-cited reference" in result.reasoning
    assert result.model_reasoning[-1].verdict == "partially_supported"
    assert_coherent(result)
    _, partly = await route(ctx_with_cocited(), _dispute(), answer_all(FRAMING, ABSENT))
    assert (partly.verdict, partly.consensus_type) == ("partially_supported", "disputed")
    assert partly.unsupported_elements == [E3] and partly.needs_user_review
    assert_coherent(partly)


async def test_partial_disputed_by_a_negative_cross_check_is_never_cleared() -> None:
    verifier = with_elements(haiku("partially_supported", supports=False), E1)
    confirm = with_elements(luna("not_supported", supports=False), E3)
    calls: list[dict[str, object]] = []
    out, result = await route(ctx_with_cocited(), {"verifier": [verifier], "confirm": [confirm]},
                              answer_all(FRAMING, COCITED), calls)
    assert calls[0]["variables"]["elements"] == [E1, E3]  # type: ignore[index]
    assert out.adjudication is not None and out.adjudication.outcome == "held"
    assert (result.verdict, result.consensus_type) == ("partially_supported", "disputed")
    assert result.unsupported_elements == [E1] and result.needs_user_review
    assert_coherent(result)


def _both_partial() -> dict[str, list[LayerResult]]:
    """Both models partial, neither with a supports quote: the verifier's label is shown."""
    return {"verifier": [with_elements(haiku("partially_supported", supports=False), E1)],
            "confirm": [with_elements(luna("partially_supported", supports=False), E3)]}


async def test_confirmed_partial_checks_both_models_elements() -> None:
    calls: list[dict[str, object]] = []
    out, result = await route(ctx_with_cocited(), _both_partial(), answer_all(FRAMING, ABSENT),
                              calls)
    assert calls[0]["variables"]["elements"] == [E1, E3]  # type: ignore[index]
    assert result.verdict == "partially_supported" and result.unsupported_elements == [E3]
    assert result.consensus_type == "adjudicated" and result.needs_user_review
    assert_coherent(result)


@pytest.mark.parametrize(("answers", "verdict"), [
    ((COCITED, COCITED), "partially_supported"),  # a co-cited abstract is not this source
    ((FRAMING, COCITED), "supported"),  # framing quotes its factual core from this source
    ((FRAMING, STATED), "supported"),  # the stated quote is validated in the pack
])
async def test_supported_needs_a_validated_supports_quote(answers: tuple[Answer, ...],
                                                         verdict: str) -> None:
    out, result = await route(ctx_with_cocited(), _both_partial(), answer_all(*answers))
    assert result.verdict == verdict and result.needs_user_review
    assert out.adjudication is not None
    assert out.adjudication.outcome == ("cleared" if verdict == "supported" else "held")
    if verdict == "supported":
        assert result.evidence_quotes and result.consensus_type == "adjudicated"
    else:
        assert result.unsupported_elements == [E1] and "no source quote" in result.reasoning
    assert_coherent(result)


async def test_unusual_positive_dispute_asks_about_both_sides() -> None:
    verifier = with_elements(haiku("supported"), E1)
    confirm = with_elements(luna("partially_supported"), "two stage scheme", E2, E3)
    calls: list[dict[str, object]] = []
    out, result = await route(ctx_with_cocited(), {"verifier": [verifier], "confirm": [confirm]},
                              answer_all(FRAMING, WORDING, ABSENT), calls)
    asked = calls[0]["variables"]["elements"]  # type: ignore[index]
    assert asked == ["two stage scheme", E2, E3]  # deduplicated union, shown layer first
    assert result.verdict == "partially_supported" and result.unsupported_elements == [E3]
    assert result.consensus_type == "disputed" and result.needs_user_review
    assert_coherent(result)


@pytest.mark.parametrize(("verifier", "confirm"), [
    ("not_supported", "not_supported"), ("contradicted", "contradicted"),
    ("not_relevant", "not_relevant"), ("contradicted", "supported"),
])
async def test_never_runs_on_negative_verdicts(verifier: str, confirm: str) -> None:
    first = with_elements(haiku(verifier, role_quote="closest"), E1)
    calls: list[dict[str, object]] = []
    out, result = await route(ctx_with_cocited(), {"verifier": [first],
                                                   "confirm": [luna(confirm)]},
                              answer_all(WORDING), calls)
    assert not calls and out.adjudication is None and "adjudicate" not in result.layer_path
    assert_coherent(result)


async def test_never_runs_on_supported_or_undecided() -> None:
    calls: list[dict[str, object]] = []
    _, supported = await route(ctx_with_cocited(), {"verifier": [haiku("supported")]},
                               answer_all(WORDING), calls)
    undecided = haiku("insufficient_evidence", supports=False)
    _, cannot = await route(ctx_with_cocited("abstract_only"), {"verifier": [undecided]},
                            answer_all(WORDING), calls)
    assert not calls and supported.verdict == "supported" and cannot.verdict == "cannot_verify"
