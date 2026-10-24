"""V5.8 experimental round-2 rules (v57.OPT_IN, off unless REFCHECK_V57_ENABLE lists
them): #20 screen tie-break, #24 twin clearance, #25 disjunct / initialism about-check."""

import pytest

from refcheck.stages.verify_claims.dispute import negative_shown, screen_tie_break
from refcheck.stages.verify_claims.round2_rules import about_parts, twin_of
from tests.unit.verify_fakes import layer, screen

OFF = "REFCHECK_V57_DISABLE"
ON = "REFCHECK_V57_ENABLE"


def test_twin_of_is_opt_in_and_symmetric(monkeypatch: pytest.MonkeyPatch) -> None:
    cleared = [("macrophage polarisation toward M2 phenotype", "q1"), ("other point", None)]
    survivor = "polarisation of macrophage phenotype toward M2"
    assert twin_of(survivor, cleared) is None  # experimental: off by default
    monkeypatch.setenv(ON, "24")
    assert twin_of(survivor, cleared) == cleared[0][0]
    assert twin_of(survivor, cleared, "overstated") is None  # never a degree survivor
    assert twin_of("vascular density", cleared) is None
    assert twin_of("other point", [("other point", "q")]) is None  # the same element
    assert twin_of("M2", cleared) is None  # one content word is never enough
    monkeypatch.setenv(OFF, "24")
    assert twin_of(survivor, cleared) is None


@pytest.mark.parametrize("survivor", [
    "hydrogel does not reduce graft rejection",  # negation
    "hydrogel always reduces graft rejection",  # quantifier
    "hydrogel alone reduces graft rejection",  # exclusivity
    "hydrogel reduces graft rejection in human recipients",  # population
    "hydrogel reduces graft rejection by 40%",  # number
    "hydrogel increased graft survival",  # another content word
])
def test_twin_never_adds_a_qualifier(monkeypatch: pytest.MonkeyPatch, survivor: str) -> None:
    from refcheck.stages.verify_claims.round2_rules import is_twin
    monkeypatch.setenv(ON, "24")
    assert not is_twin(survivor, "hydrogel reduces graft rejection")
    assert not is_twin("hydrogel decreased graft survival", "hydrogel increased graft survival")


def test_about_parts_disjunct_and_initialism(monkeypatch: pytest.MonkeyPatch) -> None:
    quote = "the implants provoked a strong foreign body reaction in rats"
    assert not about_parts("FBR to the implants", quote)  # experimental: off by default
    monkeypatch.setenv(ON, "25")
    assert about_parts("FBR to the implants", quote)
    assert not about_parts("FBR", quote)  # one content word is never "about" it
    assert about_parts("fibrous encapsulation or foreign body reaction", quote)
    assert not about_parts("fibrous encapsulation and vascular ingrowth", quote)
    assert not about_parts("FBR was reduced", "For both rats, fibrosis was reduced")
    assert not about_parts("FBR to the implants",  # a skipped word breaks the initialism
                           "the implants provoked a foreign body giant cell reaction")
    monkeypatch.setenv(OFF, "25")
    assert not about_parts("FBR to the implants", quote)


def test_screen_tie_break(monkeypatch: pytest.MonkeyPatch) -> None:
    probs = screen(0.9, topic=0.85).probs
    assert not screen_tie_break("not_supported", "supported", probs, quoted=True)  # opt-in
    monkeypatch.setenv(ON, "20")
    assert screen_tie_break("not_supported", "supported", probs, quoted=True)
    assert not screen_tie_break("not_supported", "supported", probs)  # no validated quote
    assert not screen_tie_break("not_relevant", "supported", probs, quoted=True)  # one step
    assert not screen_tie_break("contradicted", "supported", probs, quoted=True)
    assert not screen_tie_break("not_supported", "partially_supported", probs, quoted=True)
    assert not screen_tie_break("not_supported", "supported", probs, fragment=True, quoted=True)
    assert not screen_tie_break("not_supported", "supported", screen(0.6).probs, quoted=True)
    assert not screen_tie_break("not_supported", "supported", screen(0.9, topic=0.7).probs,
                                quoted=True)
    assert not screen_tie_break("not_supported", "supported", {}, quoted=True)  # no screen
    confirm = layer("confirm", "supported")
    shown, notes = negative_shown("not_supported", confirm, False, False, screen(0.9))
    assert shown == "supported" and notes[0].startswith("Screen tie-break")
    unquoted = layer("confirm", "supported", supports=False)
    assert negative_shown("not_supported", unquoted, False, False, screen(0.9)) == (
        "partially_supported", [])
    assert negative_shown("not_relevant", confirm, False, False, screen(0.9)) == (
        "not_supported", [])
    assert negative_shown("not_supported", confirm, False, False, None) == (
        "partially_supported", [])
    monkeypatch.setenv("REFCHECK_DISPUTE_POLICY", "strict")
    assert not screen_tie_break("not_supported", "supported", probs, quoted=True)
    monkeypatch.setenv("REFCHECK_DISPUTE_POLICY", "soften")
    monkeypatch.setenv(OFF, "20")
    assert not screen_tie_break("not_supported", "supported", probs, quoted=True)
