"""V5.6 L1: a figure credit is judged on its legend panel (claims, context, dispute rule)."""

import time
from unittest.mock import patch

from refcheck.stages.verify_claims.calibration import ScreenThresholds
from refcheck.stages.verify_claims.cascade import focus_query, run_cascade
from refcheck.stages.verify_claims.credit import (
    PANEL_PREFIX,
    figure_credit,
    panel_claim,
    panel_of,
    provenance_only,
    with_credit_panels,
)
from refcheck.stages.verify_claims.credit_position import credit_occurrences
from refcheck.stages.verify_claims.dispute import credit_line
from refcheck.stages.verify_claims.layers import LayerResult, cited_for
from tests.unit.credit_fakes import LEGEND, PANEL_A, PANEL_B, PANEL_C, POE, ROE, credit_claim, strip
from tests.unit.verify_fakes import layer, make_claim, make_ctx

_ON = ScreenThresholds()


def test_panel_claim_replaces_only_cited_for() -> None:
    claim = credit_claim()
    prepared = panel_claim(claim, 1)
    assert prepared.cited_for == PANEL_PREFIX + strip(PANEL_C)
    assert panel_of(prepared) == strip(PANEL_C)
    # the claim shown to the user keeps its own text
    assert (prepared.manuscript_text, prepared.extracted_claim) == (ROE, ROE)
    assert prepared.paragraph_text == LEGEND and claim.cited_for == "Adapted from Roe et al"
    assert panel_claim(prepared) is prepared  # idempotent


def test_claims_without_panel_text_are_unchanged() -> None:
    ordinary = make_claim()
    assert panel_claim(ordinary) is ordinary and panel_of(ordinary) is None
    body = credit_claim(paragraph="Hydrogels release drugs locally. " + ROE + " They degrade.")
    assert panel_claim(body) is body


def test_repeated_credits_are_told_apart_by_their_offsets() -> None:
    claims = [credit_claim(1, base=2440, nth=0), credit_claim(2, POE, base=2440, ref_id=2),
              credit_claim(3, base=2440, nth=1)]
    assert credit_occurrences(claims) == {1: 0, 2: 0, 3: 1}
    prepared = with_credit_panels(claims)
    assert [panel_of(c) for c in prepared] == [strip(PANEL_A), strip(PANEL_B), strip(PANEL_C)]


def test_windowed_paragraphs_use_the_detector_offsets() -> None:
    # Each claim sees its own window of a long legend: same sentence, different text.
    first = credit_claim(1, base=900, nth=0)
    window = "…recipients. " + LEGEND[LEGEND.index(PANEL_A):]
    shift = LEGEND.index(PANEL_A) - len("…recipients. ")
    second = credit_claim(2, paragraph=window, base=900 + shift, nth=1)
    assert credit_occurrences([first, second]) == {1: 0, 2: 1}
    assert panel_of(with_credit_panels([first, second])[1]) == strip(PANEL_C)


def test_without_offsets_every_identical_credit_panel_is_judged() -> None:
    prepared = with_credit_panels([credit_claim()])[0]
    assert panel_of(prepared) == f"{strip(PANEL_A)}. {strip(PANEL_C)}"


def test_pair_context_judges_the_panel() -> None:
    ctx = make_ctx(panel_claim(credit_claim(), 0))
    assert ctx.credit_panel == strip(PANEL_A)
    assert ctx.claim_text.startswith("Adapted from Roe et al")  # the sentence (markers out)
    part = cited_for(ctx.claim, ctx.claim_text)
    assert part.startswith(PANEL_PREFIX + "(A) Fluorescence images")
    assert focus_query(ctx.claim, ctx.claim_text).startswith(PANEL_PREFIX + "(A)")
    # a raw credit claim gets its panel in build_pair_context too
    assert make_ctx(credit_claim()).credit_panel == panel_of(with_credit_panels(
        [credit_claim()])[0])


def test_provenance_only_is_a_credit_without_panel_text() -> None:
    assert not provenance_only(make_ctx(credit_claim()))
    body = credit_claim(paragraph="Hydrogels release drugs locally. " + ROE + " They degrade.")
    assert provenance_only(make_ctx(body))
    assert not provenance_only(make_ctx())
    assert figure_credit(make_ctx(credit_claim())) and figure_credit(make_ctx(body))
    assert not figure_credit(make_ctx())


def test_dispute_credit_exception_only_for_provenance_only_credits() -> None:
    confirm = layer("confirm", "supported")
    assert not credit_line(make_ctx(credit_claim()), confirm)
    body = credit_claim(paragraph="Hydrogels release drugs locally. " + ROE + " They degrade.")
    assert credit_line(make_ctx(body), confirm)
    assert not credit_line(make_ctx(body), layer("confirm", "supported", supports=False))


async def _route(claim_ctx: object) -> str:
    script = {"verifier": [layer("verifier", "not_relevant", role_quote="closest")],
              "confirm": [layer("confirm", "supported")]}

    async def fake_run_layer(role: str, pack: object, claim: object, ctx: object,
                             template: str, **kwargs: object) -> LayerResult:
        return script[str(kwargs["layer"])].pop(0)

    with patch("refcheck.stages.verify_claims.cascade.run_layer", fake_run_layer):
        out = await run_cascade(claim_ctx, None, _ON,  # type: ignore[arg-type]
                                deadline=time.monotonic() + 100)
    return out.verdict


async def test_panel_credit_dispute_is_softened_one_step() -> None:
    assert await _route(make_ctx(credit_claim())) == "not_supported"


async def test_provenance_only_credit_dispute_shows_the_cross_check() -> None:
    body = credit_claim(paragraph="Hydrogels release drugs locally. " + ROE + " They degrade.")
    assert await _route(make_ctx(body)) == "supported"
