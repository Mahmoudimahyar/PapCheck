"""V5.7 clearing rules: diff-based disqualifier (#3), loose about-check (#5), the slot
lexicon and abbreviation definitions (synthetic texts only)."""

import pytest

from refcheck.stages.verify_claims.abbrev import best_long_form, definitions, expand
from refcheck.stages.verify_claims.clear_rules import about_element, about_loose, disqualifier
from refcheck.stages.verify_claims.slot_lexicon import phrase_in, stated_in, synonyms_in


@pytest.mark.parametrize(("element", "quote", "why"), [
    # a disqualifying phrase the quote states (or a lexicon synonym of it) is fine
    ("closely match human anatomy", "anatomically more similar to humans than rodents",
     None),
    ("may still require systemic support", "local therapy is necessary to delay rejection",
     None),
    ("graft loss caused by the portal site",
     "infusion at the portal site can cause graft loss early", None),
    ("performed annually", "about one million procedures per year worldwide", None),
    # ... but not one it does not state
    ("Patients often wait for weeks", "in most trials the waiting lists grew",
     "a population or model"),
    ("performed every year", "about one million procedures worldwide", "a time frame"),
    # a cause connective is stated only with its object
    ("delays due to poor road access",
     "a 30% delay rate due to strikes and storms", "a mechanism or cause"),
    # specificity / exclusivity and relational verbs (V5.7 #3 additions)
    ("a myeloid-cell specific restriction", "it restricts infection in myeloid cells",
     "a specificity or exclusivity qualifier"),
    ("ICS may down-regulate ACE2, thereby lowering binding",
     "ICS use was associated with lower ACE2 expression", "a mechanism or cause"),
    # hedges: a negated universal, a need or exclusivity word in a modal author reading
    ("not universally effective", "the gel was effective in some recipients", None),
    ("solely local therapy may still require support", "local therapy needed support", None),
    ("in all patients", "effective in some patients", "a frequency or universality word"),
    # numbers must be in the quote
    ("a 40% reduction", "IL-6 fell by 40% in treated mice", None),
    ("a 45% reduction", "IL-6 fell by 40% in treated mice", "a number"),
])
def test_disqualifier_is_diff_based_and_hedge_aware(element: str, quote: str,
                                                    why: str | None) -> None:
    assert disqualifier(element, quote) == why


@pytest.mark.parametrize("element", [
    "performed every year", "due to immune rejection", "in human patients", "a 40% gain",
    "an IL-6-specific effect", "thereby activating macrophages", "in all patients",
])
def test_without_a_quote_every_disqualifying_phrase_counts(element: str) -> None:
    assert disqualifier(element) is not None


def test_the_v56_disqualifier_ignores_the_quote(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFCHECK_V57_DISABLE", "3")
    assert disqualifier("in human patients", "human patients were treated") == \
        "a population or model"
    assert disqualifier("an IL-6-specific effect", "x") is None  # not a V5.6 class
    assert disqualifier("not universally effective") == "a frequency or universality word"


def test_abbreviations_come_from_the_texts_own_definitions() -> None:
    text = ("The stiffness affects the foreign body reaction (FBR) in vivo. Gelatin "
            "methacrylate (GelMA) and type 1 diabetes (T1D) were studied (n = 5).")
    assert definitions(text) == {"fbr": "foreign body reaction",
                                 "gelma": "Gelatin methacrylate", "t1d": "type 1 diabetes"}
    assert expand("reduce the FBR", text) == "reduce the FBR foreign body reaction"
    assert best_long_form("XYZ", "nothing that matches here") is None
    assert expand("FBR", "no definitions") == "FBR"


@pytest.mark.parametrize(("element", "quote", "ok"), [
    # meta word dropped + abbreviation: 3 of 4 content words
    ("foreign body response (FBR) reduction goal",
     "the stiffness of the gel affects the foreign body reaction (FBR) it induces", True),
    # abbreviation defined only in the source's passages
    ("reduce the FBR", "coatings reduce the foreign body reaction by limiting fibrosis", True),
    ("marked visual, auditory, and cognitive deficits",
     "the lesion can cause visual, auditory, and motor problems", True),
    # a generic sentence clears nothing
    ("tailored degradation profiles", "polymers provide tunable mechanical properties",
     False),
    ("recapitulate native ECM", "we proposed a kidney matrix hydrogel as a scaffold", False),
])
def test_about_loose(element: str, quote: str, ok: bool) -> None:
    definitions_text = "Implants trigger a foreign body reaction (FBR) in most hosts."
    assert about_loose(element, quote, definitions_text) is ok
    assert not about_element(element, quote) or ok


def test_about_loose_is_strict_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFCHECK_V57_DISABLE", "5")
    assert not about_loose("reduce the FBR", "coatings reduce the foreign body reaction",
                           "a foreign body reaction (FBR)")


def test_slot_lexicon() -> None:
    assert phrase_in("every year", "ten procedures a year")
    assert not phrase_in("all", "allografts were used")  # short words match whole
    assert synonyms_in("annually", "one million people per year")
    assert synonyms_in("cause", "the drug can lead to fibrosis")
    assert synonyms_in("necessary", "a step required for engraftment")
    assert not synonyms_in("rejection", "graft inflammation was transient")
    assert stated_in("in mice", "murine islets were transplanted")
    assert not stated_in("rats", "the ratio was high")


@pytest.mark.parametrize(("phrase", "text"), [
    ("every year", "survival was measured at 5 years"),  # a duration is not a frequency
    ("rats", "the effect was shown in mice after transplantation"),  # never another species
    ("mice", "islets were implanted in the flank"),
    ("humans", "rat recipients of allografts"),
    ("in vivo", "mice were treated"),
])
def test_trigger_lexicon_never_bridges_species_or_frequency(phrase: str, text: str) -> None:
    assert not stated_in(phrase, text)


@pytest.mark.parametrize(("element", "quote", "why"), [
    # V5.7 #3 uses the element's OWN slot words, never a synonym group
    ("the effect was shown in rats",
     "the effect was shown in mice after islet transplantation", "a population or model"),
    ("the effect was shown in mice",
     "islets were implanted in the flank", "a population or model"),
    ("the effect was shown in humans",
     "the effect was seen in rat recipients of allografts", "a population or model"),
    ("the graft is rejected every year",
     "Graft survival was measured at 5 years after surgery", "a time frame"),
    ("a long-term benefit", "the benefit lasted for several months", "a time frame"),
    ("the dose must be lowered", "a lower dose is critical for safety",
     "a recommendation or need"),
    # ... while a form of the same population / frequency still states it
    ("the effect was shown in mice", "the effect was shown in murine models", None),
    ("the test is repeated every year", "the test is repeated annually at each site", None),
])
def test_disqualifier_uses_the_elements_own_slot_words(element: str, quote: str,
                                                       why: str | None) -> None:
    assert disqualifier(element, quote) == why


@pytest.mark.parametrize("quote", [
    "there it was that the primates were",
    "as it was the case with hydrogel encapsulation",
])
def test_about_loose_needs_more_than_one_shared_word(quote: str) -> None:
    element = ("hydrogel encapsulation prevents fibrosis and chronic allograft rejection in "
               "nonhuman primates for years")
    assert not about_loose(element, quote)
