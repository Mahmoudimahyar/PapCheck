"""False number warnings from glued text and figures stated elsewhere (V5.6, E7).

Synthetic replicas of three reviewed glitches: a gap size stated in the Methods but
not in the quotes ("8 mm"), a figure glued to the previous word in the quote itself
("estimated to be21.3 million"), and a strain name read as a number next to a day-60
endpoint stated elsewhere ("C57BL/6" -> "6").
"""

import pytest

from refcheck.stages.verify_claims.calibration import ScreenThresholds
from refcheck.stages.verify_claims.cascade import CascadeOutcome
from refcheck.stages.verify_claims.cascade_helpers import build_result
from refcheck.stages.verify_claims.gates import extract_quantities, numeric_mismatch
from refcheck.stages.verify_claims.layers import LayerResult, validate_output_quotes
from refcheck.stages.verify_claims.post_checks import quote_surroundings, stated_elsewhere
from refcheck.stages.verify_claims.source_document import build_source_document
from refcheck.stages.verify_claims.source_numbers import numbers_missing_from_source, quantities
from refcheck.stages.verify_claims.verifier_helpers import build_pair_context
from tests.unit.verify_fakes import judge_output, make_claim, make_pack, make_ref

_ON = ScreenThresholds()


@pytest.mark.parametrize(("claim", "source"), [
    ("a 10 mg/kg dose", "a 10mg/kg dose"), ("a 10mg dose", "a 10 mg dose"),
    ("an 8 mm gap", "an 8-mm gap"), ("a 5x increase", "a 5-fold increase"),
    ("after 24 h", "after 24h"), ("for 60 days", "for 60days"),
    ("n = 12 rats", "n=12 rats"), ("p < 0.05", "p<0.05"),
    ("reach 21.3 million", "estimated to be21.3 million"),
    ("reach 21.3 million", "estimated to be21.3million"),
])
def test_glued_figures_are_found(claim: str, source: str) -> None:
    assert numbers_missing_from_source(claim, source) == []


@pytest.mark.parametrize("text", ["IL6 and CD4+ cells", "C57BL/6 mice", "C57BL/6J mice",
                                  "Th17 and Foxp3", "DBA/2 mice", "3D gels"])
def test_names_stay_names(text: str) -> None:
    assert quantities(text, source=True) == [] and extract_quantities(text, source=True) == []


def test_a_figure_glued_to_the_word_before_it_in_the_quote() -> None:  # replica of 135
    claim = "The number is projected to reach 21.3 million by 2052."
    quote = "The projected population for 2052 is estimated to be21.3 million."
    assert numeric_mismatch(claim, [quote]) is None


def test_a_strain_digit_is_not_a_quoted_number() -> None:  # replica of 163
    claim = "Gel G corrected glycemia for 60 days, outperforming alginate."
    quotes = ["All animals receiving gel G reverted, as opposed to only 50% with alginate",
              "Capsules were implanted into diabetic C57BL/6 mice"]
    assert numeric_mismatch(claim, quotes) is None


_METHODS = ("Methods\n\nAn 8 mm segment of the nerve was resected in each rat. "
            + "Animals were housed under standard conditions with free access to food. " * 14
            + "\n\nResults\n\nAll grafts were retrieved 60 days post-transplantation. "
            + "Body weight did not differ between groups during the study. " * 10
            + "Conduits with gel G gave responses equivalent to autograft (0.13 mV vs "
            "0.12 mV, p > 0.99). Women made up 30% of the staff.")
_QUOTE = "Conduits with gel G gave responses equivalent to autograft (0.13 mV vs 0.12 mV"


def _result(claim_text: str) -> tuple[str, str]:
    doc = build_source_document(1, _METHODS, abstract_text="A nerve gap study of gel G.")
    pack = make_pack(texts=(_QUOTE + ", p > 0.99).",), abstract=None)
    ctx = build_pair_context(make_claim(claim_text), make_ref(), doc, pack)
    out = judge_output("supported", [("P1", _QUOTE, "supports")])
    validated, _ = validate_output_quotes(out, pack)
    lay = LayerResult(layer="verifier", role="verifier", output=out, validated_quotes=validated)
    outcome = CascadeOutcome(verdict="supported", label_layer=lay, decided_by="verifier",
                             consensus_type="verifier", tier=2, layers=[lay],
                             layer_path=["verifier"])
    return quote_surroundings(ctx, [lay]), build_result(ctx, None, outcome, _ON, 1).reasoning


@pytest.mark.parametrize("claim", [
    "Gel G in rats (8 mm sciatic gap) matched the autograft response.",  # replica of 128
    "Gel G matched the autograft response over 60 days.",
])
def test_a_figure_stated_elsewhere_with_its_unit_or_kind_is_no_warning(claim: str) -> None:
    near, reasoning = _result(claim)
    assert stated_elsewhere(claim, _METHODS) and "do not appear in the quoted evidence" \
        not in reasoning


@pytest.mark.parametrize("claim", [
    "Gel G matched the autograft response in 8 rats.",  # a bare "8": the paper's "8 mm" is not it
    "Gel G matched the autograft response in 60 rats.",  # the paper's "60" counts days
])
def test_a_bare_figure_stated_elsewhere_is_still_a_warning(claim: str) -> None:
    _, reasoning = _result(claim)
    assert "do not appear in the quoted evidence" in reasoning
