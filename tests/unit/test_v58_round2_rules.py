"""V5.8 round-2 rules (G6): pure helpers and their REFCHECK_V57_DISABLE switches."""

import pytest

from refcheck.stages.verify_claims.adjudicate_rules import ElementDecision
from refcheck.stages.verify_claims.check_first import missing_named
from refcheck.stages.verify_claims.cocited_union_pack import DEFICIT_TERMS, search_query
from refcheck.stages.verify_claims.framing_rules import is_scaffold
from refcheck.stages.verify_claims.round2_rules import (
    edge_trimmed,
    hedged_stated,
    overstated_as_wording,
)
from refcheck.stages.verify_claims.slot_audit import polarity_slots
from refcheck.stages.verify_claims.subtype_round2 import refined_type
from tests.unit.verify_fakes import layer

OFF = "REFCHECK_V57_DISABLE"
ON = "REFCHECK_V57_ENABLE"  # the experimental (opt-in) proposals: v57.OPT_IN


def test_edge_trimmed_drops_only_function_words() -> None:
    assert edge_trimmed("a bipedal, fully grown model of the") == "bipedal, fully grown model"
    assert edge_trimmed("the gel and") == "gel"
    assert edge_trimmed("gel lowered IL-6") == "gel lowered IL-6"


def test_hedged_stated(monkeypatch: pytest.MonkeyPatch) -> None:
    assert hedged_stated("stated", "The abstract does not explicitly say barrier.")
    assert hedged_stated("stated", "paraphrase-level match")
    assert not hedged_stated("stated", "P2 states it.")
    assert not hedged_stated("wording", "not explicitly")
    monkeypatch.setenv(OFF, "22")
    assert not hedged_stated("stated", "weak match")


def test_overstated_as_wording(monkeypatch: pytest.MonkeyPatch) -> None:
    assert overstated_as_wording("overstated", "improves graft survival", "stronger wording")
    assert overstated_as_wording("overstated", "improves graft survival", "a paraphrase")
    assert not overstated_as_wording("overstated", "always improves survival", "wording")
    assert not overstated_as_wording("overstated", "reduces IL-6 by 40%", "wording")
    assert not overstated_as_wording("overstated", "improves survival", "contrary wording")
    # a note that names a stronger claim is a real overstatement, not wording
    assert not overstated_as_wording(
        "overstated", "drug X reverses established inflammation in mice",
        "the source only says anti-inflammatory; the claim says it reverses inflammation")
    assert not overstated_as_wording("overstated", "improves graft survival", "")
    monkeypatch.setenv(OFF, "27")
    assert not overstated_as_wording("overstated", "improves graft survival", "wording")


@pytest.mark.parametrize(("element", "cited", "hit"), [
    ("three phases", "Repair proceeds in three phases of healing", True),
    ("three phases", "Repair proceeds over time", False),  # the scaffold is not in the span
    ("rather than", "Gel X, rather than gel Y, degrades", True),
    ("different from autografts", "This gel, different from autografts, degrades", False),
    ("not universally effective", "Drug X is effective", False),  # negated universal: dropped
    ("even if", "It works even if given late", True),
    ("particularly in children", "It works, particularly in children", False),
    # content beyond the scaffold is a claim about the source, never framing
    ("prevented rejection even when given 7 days after transplantation",
     "Unlike tacrolimus, drug X prevented rejection even when given 7 days after "
     "transplantation.", False),
    ("no nephrotoxicity, unlike tacrolimus", "Unlike tacrolimus, drug X caused no "
     "nephrotoxicity.", False),
    ("not all recipients developed rejection", "Not all recipients developed rejection.", False),
])
def test_framing_scaffolds(element: str, cited: str, hit: bool) -> None:
    assert is_scaffold(element, cited) is hit


def test_framing_only_for_absent_elements_and_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    assert is_scaffold("three phases", "in three phases", "absent")
    assert not is_scaffold("three phases", "in three phases", "overstated")
    monkeypatch.setenv(OFF, "23")
    assert not is_scaffold("three phases", "in three phases")


def _d(element: str, category: str) -> ElementDecision:
    return ElementDecision(element=element, category=category)


def test_refined_type_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    nouns = [_d("macrophages", "absent"), _d("dendritic cells", "absent")]
    assert refined_type("unsupported_inference", nouns) == "missing_element"
    relational = [_d("macrophages reduce rejection", "absent")]
    assert refined_type("unsupported_inference", relational) == "unsupported_inference"
    alone = [_d("alone", "contradicted")]
    assert refined_type("specific_detail_mismatch", alone) == "specific_detail_mismatch"
    widely = [_d("widely used", "overstated")]
    assert refined_type("certainty_overstated", widely) == "certainty_overstated"
    monkeypatch.setenv(ON, "32,33")  # the test-derived sub-rules are opt-in
    assert refined_type("specific_detail_mismatch", [_d("alone", "contradicted")]) == \
        "certainty_overstated"
    assert refined_type("specific_detail_mismatch",
                        [_d("without systemic toxicity", "contradicted")]) == \
        "unsupported_inference"
    assert refined_type("specific_detail_mismatch", [_d("40%", "contradicted")]) == \
        "specific_detail_mismatch"
    assert refined_type("certainty_overstated", [_d("widely used", "overstated")]) == \
        "scope_overgeneralized"
    monkeypatch.setenv(OFF, "26")
    assert refined_type("unsupported_inference", nouns) == "unsupported_inference"


def test_missing_named(monkeypatch: pytest.MonkeyPatch) -> None:
    named = layer("verifier", missing="No passage explicitly says it impedes healing.")
    assert missing_named(named)
    assert not missing_named(layer("verifier", missing="Minor wording difference."))
    assert not missing_named(layer("verifier"))
    monkeypatch.setenv(OFF, "28")
    assert not missing_named(named)


def test_polarity_slots(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ON, "31")
    cited = "Graft Q is used to avoid donor morbidity"
    quotes = ["Stored graft Q is not widely used given the costs."]
    slots = polarity_slots(cited, quotes)
    assert [(s.phrase, s.against, s.partial_type) for s in slots] == [
        ("Graft Q is used", "not widely used", "unsupported_inference")]
    assert slots[0].element == "polarity: 'Graft Q is used'"
    assert polarity_slots("Graft Q is not used", quotes) == []
    assert polarity_slots(cited, ["Graft Q is used widely."]) == []
    monkeypatch.setenv(OFF, "31")
    assert polarity_slots(cited, quotes) == []


def test_union_query_expansion(monkeypatch: pytest.MonkeyPatch) -> None:
    assert search_query("hydrogels require reinforcement") == \
        f"hydrogels require reinforcement {DEFICIT_TERMS}"
    assert search_query("capillary density") == "capillary density"
    monkeypatch.setenv(OFF, "30")
    assert search_query("hydrogels require reinforcement") == "hydrogels require reinforcement"


def test_colour_key_elements_are_locked() -> None:
    from refcheck.stages.verify_claims.adjudicate_rules import is_locked
    from refcheck.stages.verify_claims.figure_key import ELEMENT_PREFIX

    assert is_locked(f"{ELEMENT_PREFIX} manuscript says CD8 green, source shows CD8 red")
    assert not is_locked("polarity: 'Graft Q is used'")
