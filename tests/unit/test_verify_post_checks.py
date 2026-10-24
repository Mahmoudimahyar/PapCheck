"""M12 (secondary citation) and M13 (claim numbers absent from the source) post-checks.

Synthetic fixtures only. Regressions for the V4.9 review: a supporting passage
that itself cited "[10, 11, 23]" was not surfaced (case 5), and figures such as
"less than 50%" / "150 kPa" that occur nowhere in the source were not flagged
(cases 17, 40).
"""

import pytest

from refcheck.stages.verify_claims.calibration import ScreenThresholds
from refcheck.stages.verify_claims.cascade import CascadeOutcome
from refcheck.stages.verify_claims.cascade_helpers import build_result
from refcheck.stages.verify_claims.layers import LayerResult, ValidatedQuote, validate_output_quotes
from refcheck.stages.verify_claims.post_checks import (
    SECONDARY_CITATION_NOTE,
    cites_other_work,
    quote_surroundings,
    secondary_citation_note,
)
from refcheck.stages.verify_claims.source_document import build_source_document
from refcheck.stages.verify_claims.verifier_helpers import PairContext, build_pair_context
from tests.unit.verify_fakes import (
    judge_output,
    layer,
    make_claim,
    make_ctx,
    make_pack,
    make_ref,
)

_ON = ScreenThresholds()
_CITING = "Older patients had a higher risk of graft failure in long-term studies [10, 11, 23]."


def _q(text: str, role: str = "supports", span: str = "", after: str = "") -> ValidatedQuote:
    return ValidatedQuote(passage_id="P1", text=text, role=role, similarity=1.0,
                          source_span=span or text, source_after=after)


@pytest.mark.parametrize("quote", [
    _CITING,
    "Hydrogels reduced rejection (Smith et al., 2019; Lee 2020).",
    "Local delivery lowered toxicity (Brown and Green, 2018).",
    "Scaffolds improved healing (3–5).",
])
def test_quote_that_cites_other_work_is_secondary(quote: str) -> None:
    assert cites_other_work(_q(quote))
    assert secondary_citation_note([_q(quote)]) == SECONDARY_CITATION_NOTE


def test_marker_dropped_from_the_quote_is_found_right_after_the_source_span() -> None:
    quote = _q("Older patients had a higher risk of graft failure",
               after=" in long-term studies [10, 11]. Next.")
    assert not cites_other_work(quote)  # the marker is not adjacent to the span
    adjacent = _q("Older patients had a higher risk of graft failure", after=" [10, 11]. Next.")
    assert cites_other_work(adjacent)


@pytest.mark.parametrize("quote", [
    "Drug X reduced IL-6 levels by 40% compared with vehicle (p < 0.01).",
    "Twelve animals were treated (12).",  # a lone parenthesised number may be a count
    "Cells were cultured (COVID-19 pandemic, 2020).",
])
def test_ordinary_quotes_are_not_secondary(quote: str) -> None:
    assert not cites_other_work(_q(quote))


def test_only_supporting_quotes_count() -> None:
    assert secondary_citation_note([_q(_CITING, role="closest")]) is None


def test_validated_quotes_keep_the_source_span_and_what_follows() -> None:
    pack = make_pack(texts=(_CITING + " Other text follows here.",))
    out = judge_output("supported", [("P1", "Older patients had a higher risk of graft "
                                            "failure in long-term studies", "supports")])
    validated, invalid = validate_output_quotes(out, pack)
    assert not invalid and validated[0].source_after.startswith(" [10, 11, 23].")
    assert cites_other_work(validated[0])


def _outcome(label: LayerResult) -> CascadeOutcome:
    return CascadeOutcome(verdict=label.verdict or "", label_layer=label, decided_by="verifier",
                          consensus_type="verifier", tier=2, layers=[label],
                          layer_path=["verifier"])


def test_secondary_citation_note_never_changes_the_verdict() -> None:
    supported = layer("verifier", "supported")
    supported.validated_quotes[0] = _q(_CITING)
    # a point the paper does not state itself (V5.6 own-statement check)
    ctx = make_ctx(make_claim("Older patients had a higher risk of graft failure."))
    result = build_result(ctx, None, _outcome(supported), _ON, 1)
    assert result.verdict == "supported" and SECONDARY_CITATION_NOTE in result.reasoning
    assert not result.needs_user_review


def test_claim_number_absent_from_the_source_adds_note_and_review() -> None:
    ctx = make_ctx(make_claim("Drug X gels reach compressive moduli of up to 150 kPa in mice."))
    result = build_result(ctx, None, _outcome(layer("verifier", "partially_supported")), _ON, 1)
    assert result.verdict == "partially_supported" and result.needs_user_review
    assert "Numbers not found in the source: 150 kPa" in result.reasoning


def test_numbers_present_in_the_source_are_not_flagged() -> None:
    ctx = make_ctx(make_claim("Drug X reduced IL-6 levels by 40% in mice [12] "
                              "(Smith et al., 2019)."))
    result = build_result(ctx, None, _outcome(layer("verifier", "supported")), _ON, 1)
    assert "Numbers not found" not in result.reasoning and not result.needs_user_review


def test_number_check_uses_only_the_part_this_reference_is_cited_for() -> None:
    claim = make_claim("Drug X reduced IL-6 by 40% and gels reach 150 kPa.", co_cited=2)
    narrowed = claim.model_copy(update={"cited_for": "Drug X reduced IL-6 by 40%"})
    result = build_result(make_ctx(narrowed), None,
                          _outcome(layer("verifier", "supported")), _ON, 1)
    assert "Numbers not found" not in result.reasoning
    whole = build_result(make_ctx(claim), None, _outcome(layer("verifier", "supported")), _ON, 1)
    assert "150 kPa" in whole.reasoning and "may come from another one" in whole.reasoning


def test_abstract_only_number_note_is_qualified() -> None:
    ctx = make_ctx(make_claim("Drug X cut inflammation by 65% in mice."), coverage="abstract_only")
    result = build_result(ctx, None, _outcome(layer("verifier", "partially_supported")), _ON, 1)
    assert "Numbers not found in the source: 65% (only the abstract was available)" \
        in result.reasoning


_TRIAL = ("Results\n\nDrug X showed a non-significant 12% reduction in mortality (p=0.08). "
          + "Follow-up visits were completed as planned in both groups. " * 12
          + "Women made up 30% of participants. In the elderly arm, a 30% reduction "
          "was seen.")


def _trial_ctx(quote_window: str) -> tuple[PairContext, LayerResult]:
    doc = build_source_document(1, _TRIAL, abstract_text="A trial of drug X.")
    pack = make_pack(texts=(quote_window,), abstract=None)
    ctx = build_pair_context(make_claim("Drug X reduced mortality by 30%."), make_ref(), doc,
                             pack)
    out = judge_output("not_supported", [("P1", "Drug X showed a non-significant 12% "
                                                "reduction in mortality", "closest")])
    validated, _ = validate_output_quotes(out, pack)
    return ctx, LayerResult(layer="verifier", role="verifier", output=out,
                            validated_quotes=validated)


def test_quoted_number_mismatch_is_kept_when_the_figure_is_only_elsewhere() -> None:
    ctx, lay = _trial_ctx(_TRIAL[9:200])  # the quote's window; "30%" is far away
    assert "30%" not in quote_surroundings(ctx, [lay])
    result = build_result(ctx, None, _outcome(lay), _ON, 1)
    assert "Numbers in the claim (30%) do not appear in the quoted evidence (12%)" \
        in result.reasoning and result.needs_user_review


def test_quoted_number_mismatch_is_waived_for_a_figure_next_to_the_quote() -> None:
    window = ("Drug X showed a non-significant 12% reduction in mortality (p=0.08); "
              "in the elderly arm the reduction was 30%.")
    ctx, lay = _trial_ctx(window)
    assert "30%" in quote_surroundings(ctx, [lay])
    result = build_result(ctx, None, _outcome(lay), _ON, 1)
    assert "do not appear in the quoted evidence" not in result.reasoning


def test_evidence_quotes_drop_a_quote_contained_in_another_layers_longer_quote() -> None:
    """V5.6 (E6): the stored evidence keeps the longer of two overlapping quotes."""
    verifier = layer("verifier", "supported")
    confirm = layer("confirm", "supported")
    short = verifier.validated_quotes[0].text.split(" (")[0]
    verifier.validated_quotes[0] = _q(short)
    out = CascadeOutcome(verdict="supported", label_layer=verifier, decided_by="verifier",
                         consensus_type="confirmed", tier=2, layers=[verifier, confirm],
                         layer_path=["verifier", "confirm"])
    result = build_result(make_ctx(), None, out, _ON, 1)
    assert result.evidence_quotes == [confirm.validated_quotes[0].text]
