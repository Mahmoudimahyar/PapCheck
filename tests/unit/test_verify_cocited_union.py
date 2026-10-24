"""Co-cited full-text union check through the real cascade (scripted layers, no network)."""

from collections.abc import Mapping

import pytest

from refcheck.models.adjudication import CocitedOutput
from refcheck.models.partial_types import GUARD_LABELS
from refcheck.stages.verify_claims.layers import LayerResult
from tests.unit.adjudicate_cascade import assert_coherent, haiku, luna, route
from tests.unit.adjudicate_fakes import (
    ABSENT,
    FRAMING,
    STATED,
    STATED_QUOTE,
    answer_all,
    enable,
    with_elements,
)
from tests.unit.union_fakes import (
    E_ABSENT,
    REF2_QUOTE,
    REF3_QUOTE,
    UnionResponder,
    cites,
    ctx_with_union,
    fake_union,
    passage_with,
    union_output,
)

E1 = "anti-inflammatory effect"


@pytest.fixture(autouse=True)
def _union_on(monkeypatch: pytest.MonkeyPatch) -> None:
    enable(monkeypatch)
    monkeypatch.setenv("REFCHECK_COCITED_UNION", "on")


def _partial(*elements: str) -> dict[str, list[LayerResult]]:
    return {"verifier": [with_elements(haiku("partially_supported"), *elements)]}


async def test_all_cleared_is_supported_with_cocited_share_and_placement_note() -> None:
    calls: list[dict[str, object]] = []
    with fake_union(cites(REF2_QUOTE), calls):
        out, result = await route(ctx_with_union(), _partial(E1, E_ABSENT),
                                  answer_all(STATED, ABSENT))
    assert [c["template"] for c in calls] == ["adjudicate_cocited"]
    assert calls[0]["variables"]["elements"] == [E_ABSENT]  # type: ignore[index]
    assert calls[0]["task"] == "verify_adjudicate_cocited"
    assert result.verdict == "supported" and result.consensus_type == "adjudicated"
    assert result.guards_applied == ["cocited_share", "overliteral_wording"]
    assert result.author_action == GUARD_LABELS["cocited_share"][1]
    assert f"Element check: '{E_ABSENT}' is stated by co-cited reference [2]" \
        in result.reasoning
    assert result.layer_path[-2:] == ["adjudicate", "adjudicate_cocited"]
    assert result.model_reasoning[-1].verdict == "supported"
    assert REF2_QUOTE not in result.evidence_quotes  # never shown as this paper's evidence
    assert out.adjudication is not None and out.adjudication.union is not None
    assert out.adjudication.union.outcome == "cleared"
    assert out.adjudication.union.cleared == {E_ABSENT: 2}
    assert_coherent(result)


@pytest.mark.parametrize("respond", [
    cites(REF3_QUOTE, passage="R2-P1"),  # reference 3's words attributed to reference 2
    cites(REF2_QUOTE, passage="R3-A"),  # reference 2's words attributed to reference 3
    cites(STATED_QUOTE, find=REF2_QUOTE),  # THIS reference's own words
    cites("Gel Q increased capillary density in healed human skin", find=REF2_QUOTE),
])
async def test_only_an_exact_quote_of_the_named_reference_clears(
        respond: UnionResponder) -> None:
    with fake_union(respond):
        out, result = await route(ctx_with_union(), _partial(E1, E_ABSENT),
                                  answer_all(STATED, ABSENT))
    assert result.verdict == "partially_supported"
    assert result.unsupported_elements == [E_ABSENT]
    assert "cocited_share" not in result.guards_applied
    assert out.adjudication is not None and out.adjudication.union is not None
    assert out.adjudication.union.outcome == "unchanged"
    assert result.layer_path[-1] == "adjudicate_cocited"
    assert_coherent(result)


async def test_some_cleared_keeps_the_partial_with_fewer_elements() -> None:
    e3 = "lower IL-6 in rat serum"

    def first_only(elements: list[str], variables: Mapping[str, object]) -> CocitedOutput:
        pid = passage_with(variables, REF2_QUOTE)
        return union_output(elements, [("cocited", pid, REF2_QUOTE), ("absent", None, None)])

    with fake_union(first_only):
        out, result = await route(ctx_with_union(), _partial(E1, E_ABSENT, e3),
                                  answer_all(STATED, ABSENT, ABSENT))
    assert result.verdict == "partially_supported" and result.unsupported_elements == [e3]
    assert f"'{e3}'" in result.author_action and E_ABSENT not in result.author_action
    assert out.adjudication is not None and out.adjudication.union is not None
    assert out.adjudication.union.outcome == "partial"
    assert_coherent(result)


async def test_disputed_pair_with_exact_quotes_is_released_but_stays_in_review() -> None:
    """V5.7 #4: every element cleared with an exact quote releases the union hold."""
    script = {"verifier": [with_elements(haiku("not_supported", role_quote="closest"),
                                         E1, E_ABSENT)], "confirm": [luna("supported")]}
    with fake_union(cites(REF2_QUOTE)):
        out, result = await route(ctx_with_union(), script, answer_all(FRAMING, ABSENT))
    assert (result.verdict, result.consensus_type) == ("supported", "disputed")
    assert result.needs_user_review and "the two models disagreed" in result.reasoning
    assert "is stated by co-cited reference [2]" in result.reasoning
    assert out.adjudication is not None and out.adjudication.union is not None
    assert out.adjudication.union.outcome == "cleared"
    assert_coherent(result)


async def test_disputed_pair_is_held_not_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFCHECK_V57_DISABLE", "4")  # the V5.6 rule
    script = {"verifier": [with_elements(haiku("not_supported", role_quote="closest"),
                                         E1, E_ABSENT)], "confirm": [luna("supported")]}
    with fake_union(cites(REF2_QUOTE)):
        out, result = await route(ctx_with_union(), script, answer_all(FRAMING, ABSENT))
    assert (result.verdict, result.consensus_type) == ("partially_supported", "disputed")
    assert result.unsupported_elements == [E_ABSENT] and result.needs_user_review
    assert "stays partially supported because the two models disagreed" in result.reasoning
    assert "is stated by co-cited reference [2]" in result.reasoning
    assert out.adjudication is not None and out.adjudication.union is not None
    assert out.adjudication.union.outcome == "held"
    assert_coherent(result)


async def test_switch_off_and_no_cocited_source_make_no_call(
        monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setenv("REFCHECK_COCITED_UNION", "off")
    with fake_union(cites(REF2_QUOTE), calls):
        _, off = await route(ctx_with_union(), _partial(E1, E_ABSENT),
                             answer_all(STATED, ABSENT))
    monkeypatch.setenv("REFCHECK_COCITED_UNION", "on")
    bare = ctx_with_union()
    bare.co_cited_docs = {}
    with fake_union(cites(REF2_QUOTE), calls):
        _, none = await route(bare, _partial(E1, E_ABSENT), answer_all(STATED, ABSENT))
    assert not calls
    for result in (off, none):
        assert result.verdict == "partially_supported"
        assert "adjudicate_cocited" not in result.layer_path
