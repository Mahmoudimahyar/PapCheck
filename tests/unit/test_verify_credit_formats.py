"""V5.6 credit panels: credits ending in "et al.", more credit formats, legend
boilerplate, abstract-only sources (synthetic legends only)."""

import pytest

from refcheck.stages.verify_claims.cascade import CascadeOutcome
from refcheck.stages.verify_claims.credit import credit_panel, panel_of, provenance_only
from refcheck.stages.verify_claims.credit_legend import credit_spans, is_credit_line, segment_labels
from refcheck.stages.verify_claims.legend_boilerplate import strip_boilerplate
from refcheck.stages.verify_claims.outcome_rules import RULE_LAYER, apply_outcome_rules
from refcheck.stages.verify_claims.source_document import (
    build_abstract_document,
    build_source_document,
)
from refcheck.stages.verify_claims.verifier_helpers import build_pair_context
from tests.unit.credit_fakes import credit_claim
from tests.unit.verify_fakes import ABSTRACT, FULL_TEXT, layer, make_pack, make_ref

SMITH = ("Islets in the hydrogel under the kidney capsule of diabetic BN rats over 90 days.")
LEE = "Graft survival curves of Lewis recipients treated with CTLA4-Ig for 100 days."


def test_a_credit_ending_in_et_al_closes_its_panel_without_labels() -> None:
    legend = (f"Figure 1. Hydrogel overview. {SMITH} Adapted from Smith et al. {LEE} "
              "Reproduced from Lee et al.")
    assert credit_panel("Reproduced from Lee et al.", legend) == LEE.rstrip(".")
    assert credit_panel("Adapted from Smith et al.", legend) == SMITH.rstrip(".")


def test_two_credits_in_one_labelled_panel_split_it() -> None:
    legend = (f"Figure 2: Two models. (A) {SMITH} Adapted from Smith et al. {LEE} Reproduced "
              "from Lee et al. (B) Skin grafts on the dorsum of rats survive longer with gel.")
    assert credit_panel("Reproduced from Lee et al.", legend) == LEE.rstrip(".")
    assert credit_panel("Adapted from Smith et al.", legend) == f"(A) {SMITH.rstrip('.')}"


def test_a_credit_followed_by_lowercase_text_runs_on_and_no_end_means_no_span() -> None:
    text = "Adapted from Smith et al. under a CC BY 4.0 license. Next panel text here."
    assert credit_spans(text, []) == [(0, text.index(" Next"))]
    endless = "Adapted from Smith et al " + "x" * 500
    assert credit_spans(endless, segment_labels(endless)) == []


@pytest.mark.parametrize("line", [
    "Adapted from Smith et al., 2019.", "Reproduced from Smith and Lee, 2019.",
    "Image adapted from Smith et al.", "Figure adapted from Smith et al.",
    "Reprinted from Smith et al. under a CC BY 4.0 license.",
    "Adapted from Smith et al. (2019).",
])
def test_common_credit_formats_are_credit_lines(line: str) -> None:
    assert is_credit_line(line)


@pytest.mark.parametrize("line", [
    "Adapted from the protocol of Smith et al., cells were grown in gel.",
    "Adapted from Smith et al. under hypoxic conditions, cells were grown.",
    "Data taken from the registry were analysed by two observers.",
])
def test_ordinary_sentences_are_not_credit_lines(line: str) -> None:
    assert not is_credit_line(line)


@pytest.mark.parametrize(("legend", "credit"), [
    (f"Figure 3. Overview. {SMITH} (Adapted from Smith et al.)", "Adapted from Smith et al."),
    (f"Figure 3. Overview. {SMITH[:-1]}, adapted from Smith et al.", "adapted from Smith et al."),
    (f"Supplementary Figure 2. Overview. {SMITH} Adapted from Smith et al.",
     "Adapted from Smith et al."),
    (f"Extended Data Fig. 4: Overview. {SMITH} Adapted from Smith et al.",
     "Adapted from Smith et al."),
])
def test_parenthesised_mid_sentence_and_supplementary_credits_get_a_panel(
        legend: str, credit: str) -> None:
    assert credit_panel(credit, legend) == SMITH.rstrip(".")


def test_legend_boilerplate_is_not_panel_content() -> None:
    panel = ("(A) Graft weight of treated rats at 60 days (n = 3 per group). Scale bar = 200 µm. "
             "Data are presented as mean ± SEM. *p < 0.05, **p < 0.01.")
    assert strip_boilerplate(panel) == "(A) Graft weight of treated rats at 60 days."
    mixed = "Survival rose to 19.5 days with one injection (top; p = 0.001). Images (bottom)."
    assert strip_boilerplate(mixed) == ("Survival rose to 19.5 days with one injection (top). "
                                        "Images (bottom).")
    legend = f"Figure 4: Weights. {panel} Adapted from Roe et al."
    assert credit_panel("Adapted from Roe et al.", legend) == (
        "(A) Graft weight of treated rats at 60 days")


def test_a_panel_with_its_own_thresholds_stays_supported() -> None:
    legend = ("Figure 4: Weights. (A) Graft weight of treated rats followed for 60 days was "
              "lower than in controls. *p < 0.05. Adapted from Roe et al.")
    source = (FULL_TEXT + " Grafts were followed for 60 days (n = 8 rats per group). Graft "
              "weight was lower than in controls. *P < 0.01 versus control.")
    claim = credit_claim(sentence="Adapted from Roe et al.", paragraph=legend)
    doc = build_source_document(1, source, abstract_text=ABSTRACT)
    ctx = build_pair_context(claim, make_ref(), doc, make_pack())
    assert ctx.credit_panel is not None and "0.05" not in ctx.credit_panel
    lay = layer("verifier", "supported")
    out = CascadeOutcome(verdict="supported", label_layer=lay, layers=[lay],
                         layer_path=["verifier"], decided_by="verifier")
    after = apply_outcome_rules(ctx, out)
    assert after.verdict == "supported" and RULE_LAYER not in after.layer_path


def test_an_abstract_only_source_keeps_the_credit_provenance_only() -> None:
    legend = f"Figure 1. Hydrogel overview. (A) {SMITH} Adapted from Roe et al."
    claim = credit_claim(sentence="Adapted from Roe et al.", paragraph=legend)
    full = build_pair_context(claim, make_ref(), build_source_document(
        1, FULL_TEXT, abstract_text=ABSTRACT), make_pack())
    assert full.credit_panel is not None and not provenance_only(full)
    abstract = build_pair_context(full.claim, make_ref(), build_abstract_document(1, ABSTRACT),
                                  make_pack(coverage="abstract_only", texts=()))
    assert abstract.credit_panel is None and panel_of(abstract.claim) is None
    assert provenance_only(abstract)
