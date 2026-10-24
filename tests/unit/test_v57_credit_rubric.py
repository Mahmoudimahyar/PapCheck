"""V5.7 #6: the credit-panel rubric after the element adjudicator (synthetic texts)."""

import pytest

from refcheck.stages.verify_claims.adjudicate import Adjudication
from refcheck.stages.verify_claims.adjudicate_rules import ElementDecision
from refcheck.stages.verify_claims.credit_rubric import (
    credit_rubric,
    panel_cleared,
    visual_only,
)
from refcheck.stages.verify_claims.layers import LayerResult
from tests.unit.adjudicate_cascade import haiku, route
from tests.unit.adjudicate_fakes import OVERSTATED, answer_all, enable, with_elements
from tests.unit.verify_fakes import FULL_TEXT, make_ctx

SOURCE = ("Grafts expressing a green fluorescent reporter persisted beyond 160 days and "
          "recipients were followed to POD 170 after transplantation.")


NO_TIME_POINTS = "Grafts expressing a green fluorescent reporter persisted for months."


@pytest.mark.parametrize(("element", "visual"), [
    ("41 post-operative days", False),  # the text states POD 170: a mismatch, not an image label
    ("POD 170 imaging", False),  # stated in the text
    ("green/red colour coding", True),  # a figure key the text never describes
    ("white arrows mark the graft", True),
    ("green fluorescence", False),  # "green" is in the text
    ("inflammation-responsive release", False),  # a substantive element
])
def test_visual_only(element: str, visual: bool) -> None:
    assert visual_only(element, SOURCE) is visual


def test_a_time_label_is_visual_only_when_the_text_states_no_time_point() -> None:
    assert visual_only("41 post-operative days", NO_TIME_POINTS)
    assert not visual_only("islet survival at day 30",
                           "Grafts were explanted on day 60, at 60 days post-transplant.")


def test_contradicted_survivors_and_bare_may_notes_stay() -> None:
    adj = _adj(("41 post-operative days", "contradicted", "The source reports another day."),
               ("complete reversal of diabetes", "overstated",
                "Glucose fell, but it may not be complete."),
               ("an effect seen only in rats", "overstated",
                "The source suggests the effect only as a potential mechanism."))
    out = credit_rubric(_credit_ctx(), adj)
    assert [(d.category, d.cleared) for d in out.decisions] == [
        ("contradicted", False), ("overstated", False), ("panel_hedge", True)]


def _adj(*decisions: tuple[str, str, str]) -> Adjudication:
    meta = LayerResult(layer="adjudicate", role="adjudicator")
    return Adjudication(meta=meta, decisions=[
        ElementDecision(element=e, category=c, note=n) for e, c, n in decisions])


def _credit_ctx(panel: bool = True):  # type: ignore[no-untyped-def]
    ctx = make_ctx()
    ctx.credit_panel = "(A) Graft imaging over time, green/red key." if panel else None
    return ctx


def test_rubric_clears_visual_and_hedge_survivors_on_a_panel_only() -> None:
    adj = _adj(("green/red colour coding", "absent", "No passage describes the key."),
               ("definite elimination of T cells", "overstated",
                "The source presents it only as a potential mechanism."),
               ("translational feasibility in pigs", "overstated",
                "Only trafficking was assessed; no efficacy."),  # a weaker result stays
               ("a 5-fold increase", "overstated", "The source may say 3-fold."))
    out = credit_rubric(_credit_ctx(), adj)
    assert [(d.category, d.cleared) for d in out.decisions] == [
        ("panel_visual", True), ("panel_hedge", True), ("overstated", False),
        ("overstated", False)]
    assert "check the source figure" in out.decisions[0].note and panel_cleared(out)
    assert credit_rubric(_credit_ctx(panel=False), adj) is adj  # not a panel credit


def test_rubric_is_switchable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFCHECK_V57_DISABLE", "6")
    adj = _adj(("green/red colour coding", "absent", ""))
    assert credit_rubric(_credit_ctx(), adj) is adj


async def test_a_panel_credit_with_only_a_dropped_hedge_is_supported_with_review(
        monkeypatch: pytest.MonkeyPatch) -> None:
    enable(monkeypatch)
    ctx = _credit_ctx()
    assert "potential" not in FULL_TEXT
    script = {"verifier": [with_elements(haiku("partially_supported"),
                                         "definite elimination of T cells",
                                         ptype="certainty_overstated")]}
    _, result = await route(ctx, script, answer_all(OVERSTATED))  # note: "The source hedges."
    assert result.verdict == "supported" and result.needs_user_review
    assert "a hedge dropped by the figure legend" in result.reasoning
