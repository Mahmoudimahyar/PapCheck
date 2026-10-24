"""V5.7 #7 (fragment / anaphoric spans) and #8 (the cross-check never upgrades a partial)."""

import pytest

from refcheck.stages.verify_claims.dispute import disputed_verdict
from refcheck.stages.verify_claims.fragment import FRAGMENT_NOTE, anaphoric, fragment_span
from refcheck.stages.verify_claims.verifier_helpers import PairContext
from tests.unit.adjudicate_cascade import assert_coherent, haiku, luna, route
from tests.unit.adjudicate_fakes import (
    ABSENT,
    STATED,
    answer_all,
    ctx_with_cocited,
    enable,
    with_elements,
)
from tests.unit.verify_fakes import make_claim

E1, E2 = "hypoxia protection", "anti-inflammatory effect"


@pytest.fixture(autouse=True)
def _on(monkeypatch: pytest.MonkeyPatch) -> None:
    enable(monkeypatch)


def fragment_ctx(text: str = "Combining both features", quality: str = "ok",
                 ) -> PairContext:
    ctx = ctx_with_cocited()
    ctx.claim = make_claim(text).model_copy(update={"claim_quality": quality})
    ctx.claim_text = text
    return ctx


def test_anaphoric_spans() -> None:
    assert anaphoric("Combining both features")
    assert anaphoric("These approaches")
    assert anaphoric("such hydrogels")
    assert not anaphoric("These results show that drug X lowers IL-6 in treated mice")  # long
    assert not anaphoric("Drug X reduces inflammation")
    assert not anaphoric("Thesis work")  # whole word only
    assert not anaphoric("")


@pytest.mark.parametrize("span", [
    "such as colon cancer", "such as alginate or chitosan hydrogels", "both in vitro and in vivo",
])
def test_list_and_example_spans_are_not_anaphoric(span: str) -> None:
    assert not anaphoric(span)


def test_fragment_span_uses_claim_quality_and_skips_credits() -> None:
    assert fragment_span(fragment_ctx())
    assert fragment_span(fragment_ctx("Hydrogel barriers and beyond", quality="fragment"))
    assert not fragment_span(fragment_ctx("Drug X reduces inflammation in mice."))
    assert not fragment_span(fragment_ctx("Adapted from these authors", quality="fragment"))


def test_disputed_verdict_never_softens_a_fragment() -> None:
    assert disputed_verdict("not_supported", "supported", fragment=True) == "not_supported"
    assert disputed_verdict("not_supported", "supported") == "partially_supported"


async def test_fragment_dispute_keeps_the_verifier_verdict() -> None:
    verifier = with_elements(haiku("not_supported", role_quote="closest"), E1, E2)
    calls: list[dict[str, object]] = []
    out, result = await route(fragment_ctx(), {"verifier": [verifier],
                                               "confirm": [luna("supported")]},
                              answer_all(STATED, STATED), calls)
    assert result.verdict == "not_supported" and result.consensus_type == "disputed"
    assert result.needs_user_review and FRAGMENT_NOTE in out.notes and calls == []


async def test_fragment_dispute_softens_when_switched_off(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFCHECK_V57_DISABLE", "7")
    verifier = with_elements(haiku("not_supported", role_quote="closest"), E1, E2)
    out, _ = await route(fragment_ctx(), {"verifier": [verifier],
                                          "confirm": [luna("supported")]},
                         answer_all(ABSENT, ABSENT))
    assert out.verdict == "partially_supported" and FRAGMENT_NOTE not in out.notes


async def test_fragment_partial_is_never_cleared_to_supported() -> None:
    verifier = with_elements(haiku("partially_supported"), E1)
    out, result = await route(fragment_ctx(), {"verifier": [verifier]}, answer_all(STATED))
    assert result.verdict == "partially_supported" and result.unsupported_elements == [E1]
    assert out.adjudication is not None and out.adjudication.outcome == "held"
    assert result.needs_user_review and FRAGMENT_NOTE in out.notes
    assert any(n.startswith(f"Element check: '{E1}'") for n in out.notes)
    assert_coherent(result)


async def test_ordinary_partial_is_still_cleared() -> None:
    verifier = with_elements(haiku("partially_supported"), E1)
    _, result = await route(fragment_ctx("Drug X reduces inflammation in mice."),
                            {"verifier": [verifier]}, answer_all(STATED))
    assert result.verdict == "supported"


async def test_cross_check_never_upgrades_a_partial() -> None:
    verifier = with_elements(haiku("partially_supported", supports=False), E1)
    calls: list[dict[str, object]] = []
    out, result = await route(ctx_with_cocited(), {"verifier": [verifier],
                                                   "confirm": [luna("supported")]},
                              answer_all(ABSENT), calls)
    assert out.label_layer is not None and out.label_layer.layer == "verifier"
    assert result.verdict == "partially_supported" and result.needs_user_review
    assert calls[-1]["variables"]["elements"] == [E1]  # type: ignore[index]
    assert any("never upgrades" in n for n in out.notes)
    assert_coherent(result)


async def test_cross_check_upgrade_when_switched_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFCHECK_V57_DISABLE", "8")
    verifier = with_elements(haiku("partially_supported", supports=False), E1)
    _, result = await route(ctx_with_cocited(), {"verifier": [verifier],
                                                 "confirm": [luna("supported")]},
                            answer_all(ABSENT))
    assert result.verdict == "supported"


async def test_supported_verifier_still_takes_the_cross_check_quotes() -> None:
    verifier = haiku("supported", supports=False)
    out, result = await route(ctx_with_cocited(), {"verifier": [verifier],
                                                   "confirm": [luna("supported")]},
                              answer_all(ABSENT))
    assert out.label_layer is not None and out.label_layer.layer == "confirm"
    assert result.verdict == "supported"
