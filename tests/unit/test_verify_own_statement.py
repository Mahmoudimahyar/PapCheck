"""Secondary-citation note only when the paper does not state the point itself (V5.6, E5),
and the provenance-only figure-credit note (L1). Synthetic text only."""

import pytest

from refcheck.stages.verify_claims.cascade import CascadeOutcome
from refcheck.stages.verify_claims.layers import LayerResult, ValidatedQuote
from refcheck.stages.verify_claims.markers import has_marker
from refcheck.stages.verify_claims.outcome_rules import CREDIT_NOTE, apply_outcome_rules
from refcheck.stages.verify_claims.own_statement import own_statement
from refcheck.stages.verify_claims.post_checks import (
    SECONDARY_CITATION_NOTE,
    secondary_citation_note,
)
from refcheck.stages.verify_claims.source_document import build_source_document
from refcheck.stages.verify_claims.verifier_helpers import PairContext, build_pair_context
from tests.unit.verify_fakes import layer, make_claim, make_pack, make_ref

CLAIM = "Local depots of drug X kept serum levels of drug X undetectable in rats."
SECONDARY = "Local depots of drug X kept serum levels undetectable in rats [12, 13]."
OWN = "In our rats, serum levels of drug X stayed undetectable with the local depot."
FILLER = "Animals were housed under standard conditions with free access to food. " * 10


def _q(text: str, role: str = "supports", context: str = "") -> ValidatedQuote:
    return ValidatedQuote(passage_id="P1", text=text, role=role, similarity=1.0,
                          source_span=text, context=context)


def _ctx(full_text: str, abstract: str = "A study of gel depots.") -> PairContext:
    doc = build_source_document(1, full_text, abstract_text=abstract)
    ctx = build_pair_context(make_claim(CLAIM), make_ref(), doc, make_pack())
    ctx.use_embeddings = False
    return ctx


def _doc(results: str, intro: str = "") -> str:
    return (f"Introduction\n\n{SECONDARY} {intro} {FILLER}\n\nResults\n\n{results} {FILLER}"
            "\n\nDiscussion\n\nGel depots are promising. " + FILLER)


@pytest.mark.parametrize(("sentence", "marked"), [
    ("Depots worked [12].", True), ("Depots worked (3–5).", True),
    ("Depots worked (Lee et al., 2019).", True), ("Lee et al. (2019) showed it.", True),
    ("Depots worked in mice27, 28.", True), ("Depots worked in 12 (40%) rats.", False),
    ("Depots worked in our rats.", False),
])
def test_has_marker(sentence: str, marked: bool) -> None:
    assert has_marker(sentence) == marked


def test_a_marker_free_supporting_quote_outside_the_introduction_suppresses_the_note() -> None:
    quote = "Serum levels of drug X were never detected in any of our rats."
    in_results = _ctx(_doc(quote))
    assert secondary_citation_note([_q(SECONDARY), _q(quote)], in_results) is None
    assert secondary_citation_note([_q(SECONDARY), _q(quote)]) == SECONDARY_CITATION_NOTE
    for other in (_q(quote, context="design only"), _q(quote, role="closest")):
        note = secondary_citation_note([_q(SECONDARY), other], in_results)
        assert note == SECONDARY_CITATION_NOTE
    in_intro = _ctx(_doc("Body weight did not differ.", intro=quote))
    note = secondary_citation_note([_q(SECONDARY), _q(quote)], in_intro)
    assert note == SECONDARY_CITATION_NOTE  # an unmarked background restatement


def test_no_note_when_the_results_state_it_without_a_marker() -> None:
    ctx = _ctx(_doc(OWN))
    assert own_statement(ctx.doc, CLAIM, [_q(SECONDARY)]) == OWN
    assert secondary_citation_note([_q(SECONDARY)], ctx) is None


@pytest.mark.parametrize("results", [
    "Serum levels of drug X were undetectable in rats with local depots [14].",  # cited too
    "Body weight did not differ between groups.",  # not stated
    "ECM, matrix; DX, drug X; SL, serum levels; LD, local depots; R, rats undetectable.",  # key
])
def test_note_kept_when_the_paper_only_restates_other_work(results: str) -> None:
    ctx = _ctx(_doc(results, intro="Serum levels of drug X stay undetectable with depots."))
    assert secondary_citation_note([_q(SECONDARY)], ctx) == SECONDARY_CITATION_NOTE


def test_the_abstract_counts_as_the_paper_stating_it() -> None:
    abstract = (f"Background: gel depots may limit systemic exposure to drugs. {OWN} "
                "Conclusion: local depots are a safe way to deliver drug X to grafts.")
    ctx = _ctx(_doc("Body weight did not differ."), abstract=abstract)
    assert secondary_citation_note([_q(SECONDARY)], ctx) is None


def test_a_review_never_states_the_point_itself() -> None:
    quote = "Serum levels of drug X were never detected in any of our rats."
    ctx = _ctx(_doc(quote))
    ctx.ref = ctx.ref.model_copy(update={"title": "Local drug depots for grafts: a review"})
    assert secondary_citation_note([_q(SECONDARY), _q(quote)], ctx) == SECONDARY_CITATION_NOTE
    by_abstract = _ctx(_doc(quote), abstract=(
        "Local drug depots may protect grafts while sparing the rest of the body. In this "
        "review we summarize how depots of drug X are built, loaded and tested in rats."))
    note = secondary_citation_note([_q(SECONDARY), _q(quote)], by_abstract)
    assert note == SECONDARY_CITATION_NOTE


@pytest.mark.parametrize(("sentence", "own"), [
    ("Together, these studies show that local depots keep drug X out of the serum.", False),
    ("In our rats, serum drug X stayed below 2 ng/mL with the local depot.", True),
    ("We found that local depots kept serum drug X undetectable in our rats.", True),
])
def test_outside_results_a_quote_counts_only_when_it_reports_data(sentence: str,
                                                                  own: bool) -> None:
    text = (f"Introduction\n\n{SECONDARY} {FILLER}\n\nResults\n\nBody weight did not "
            f"differ. {FILLER}\n\nDiscussion\n\n{sentence} {FILLER}")
    note = secondary_citation_note([_q(SECONDARY), _q(sentence)], _ctx(text))
    assert (note is None) == own


def _outcome(lay: LayerResult) -> CascadeOutcome:
    return CascadeOutcome(verdict=lay.verdict or "", label_layer=lay, layers=[lay],
                          layer_path=["verifier"], decided_by="verifier")


def _credit_ctx(panel: str | None = None) -> PairContext:
    claim = make_claim("Adapted from Smith et al. (2020).")
    ctx = build_pair_context(claim, make_ref(), _ctx(_doc(OWN)).doc, make_pack())
    ctx.credit_panel = panel
    return ctx


def test_provenance_only_credit_gets_a_note_and_review() -> None:
    out = apply_outcome_rules(_credit_ctx(), _outcome(layer("verifier", "supported")))
    assert CREDIT_NOTE in out.notes and out.needs_review and out.verdict == "supported"
    again = apply_outcome_rules(_credit_ctx(), out)
    assert again.notes.count(CREDIT_NOTE) == 1


def test_no_credit_note_with_a_panel_or_a_partial() -> None:
    supported = _outcome(layer("verifier", "supported"))
    assert CREDIT_NOTE not in apply_outcome_rules(_credit_ctx("(A) Gel depots in rats"),
                                                  supported).notes
    partial = _outcome(layer("verifier", "partially_supported"))
    assert CREDIT_NOTE not in apply_outcome_rules(_credit_ctx(), partial).notes
    assert CREDIT_NOTE not in apply_outcome_rules(_ctx(_doc(OWN)), supported).notes
