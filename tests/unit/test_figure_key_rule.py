"""The colour-key outcome rule in the cascade (V5.8 G2). Synthetic PDFs and text only."""

from pathlib import Path

import pytest

from refcheck.stages.verify_claims.outcome_rules import RULE_LAYER, apply_outcome_rules
from refcheck.stages.verify_claims.verifier_helpers import PairContext
from tests.unit.adjudicate_cascade import assert_coherent, haiku, luna, route
from tests.unit.adjudicate_fakes import STATED, answer_all, ctx_with_cocited, enable, with_elements
from tests.unit.test_figure_key import RIGHT, SWAPPED, text_key_pdf
from tests.unit.verify_fakes import make_claim, make_ref


@pytest.fixture(autouse=True)
def _on(monkeypatch: pytest.MonkeyPatch) -> None:
    enable(monkeypatch)


def _ctx(tmp_path: Path, text: str = SWAPPED, panel: bool = False,
         coverage: str = "full_text") -> PairContext:
    ctx = ctx_with_cocited(coverage)
    if panel:
        ctx.claim = make_claim("Adapted from Smith et al. (2020).")
        ctx.claim_text = "Adapted from Smith et al. (2020)."
        ctx.credit_panel = text
    else:
        ctx.claim = make_claim(text)
        ctx.claim_text = text
    ctx.ref = make_ref(pdf_path=text_key_pdf(tmp_path / "source.pdf"))
    return ctx


@pytest.mark.parametrize("panel", [False, True])
async def test_a_swapped_colour_key_becomes_a_major_partial(tmp_path: Path, panel: bool) -> None:
    _, result = await route(_ctx(tmp_path, panel=panel), {"verifier": [haiku("supported")]},
                            answer_all(STATED))
    assert result.verdict == "partially_supported" and result.partial_severity == "major"
    assert result.partial_type == "specific_detail_mismatch" and result.needs_user_review
    assert result.unsupported_elements[0].startswith("colour key: manuscript says MK1⁺ green")
    assert "source figure shows MK1⁺ red" in result.author_action
    assert "Colour key check" in result.reasoning
    assert result.layer_path[-1] == RULE_LAYER
    assert_coherent(result)


async def test_the_right_colour_key_changes_nothing(tmp_path: Path) -> None:
    _, result = await route(_ctx(tmp_path, RIGHT), {"verifier": [haiku("supported")]},
                            answer_all(STATED))
    assert result.verdict == "supported" and RULE_LAYER not in result.layer_path


async def test_a_partial_gains_the_colour_element_and_becomes_major(tmp_path: Path) -> None:
    partial = with_elements(haiku("partially_supported"), "in human patients",
                            ptype="scope_overgeneralized", severity="minor")
    _, result = await route(_ctx(tmp_path), {"verifier": [partial],
                                             "confirm": [luna("partially_supported")]},
                            answer_all(("absent", None, None, "not stated")))
    assert result.partial_type == "scope_overgeneralized" and result.partial_severity == "major"
    assert result.unsupported_elements[0].startswith("colour key: ")  # first: the action
    assert "source figure shows MK1⁺ red" in result.author_action


def test_abstract_only_or_no_pdf_never_checks(tmp_path: Path) -> None:
    from refcheck.stages.verify_claims.cascade import CascadeOutcome
    lay = haiku("supported")
    out = CascadeOutcome(verdict="supported", label_layer=lay, layers=[lay],
                         layer_path=["verifier"])
    assert apply_outcome_rules(_ctx(tmp_path, coverage="abstract_only"), out) == out
    no_pdf = _ctx(tmp_path)
    no_pdf.ref = make_ref()
    assert apply_outcome_rules(no_pdf, out) == out


def test_a_co_cited_sentence_is_checked_only_when_narrowed(tmp_path: Path) -> None:
    from refcheck.stages.verify_claims.cascade import CascadeOutcome
    lay = haiku("supported")
    out = CascadeOutcome(verdict="supported", label_layer=lay, layers=[lay],
                         layer_path=["verifier"])
    ctx = _ctx(tmp_path)
    ctx.claim = make_claim(SWAPPED, co_cited=2)
    assert apply_outcome_rules(ctx, out) == out
