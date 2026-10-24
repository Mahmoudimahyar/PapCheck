"""V5.7 #15: slots of the blind slot probe - find, mask, compare (no LLM; synthetic text)."""

import pytest

from refcheck.stages.verify_claims.slot_probe_rules import (
    Slot,
    differs,
    element_for,
    find_slots,
    masked,
    not_stated,
)

CLAIM = "Local delivery of drug X justifies its use because it reduces graft loss in patients."


def _slot(kind: str, text: str) -> Slot:
    return Slot(number=1, kind=kind, text=text, window=text)  # type: ignore[arg-type]


def test_one_slot_per_kind_in_text_order() -> None:
    slots = find_slots(CLAIM)
    assert [(s.number, s.kind, s.text) for s in slots] == [
        (1, "relation", "justifies"), (2, "direction", "reduces"), (3, "population", "patients")]
    assert slots[0].window == "delivery of drug X justifies its use because it"  # 4 words


@pytest.mark.parametrize("text", [
    "Drug-induced fibrosis was mild.", "A calcineurin inhibitor and a gene promoter were used.",
    "Gel Q was stable for weeks.",
])
def test_modifiers_and_nouns_are_not_slots(text: str) -> None:
    assert find_slots(text) == []


def test_masking_hides_every_occurrence_of_the_slot_words() -> None:
    text = "Drug X reduces IL-6 and reduces TNF in mice."
    slots = find_slots(text)
    shown = masked(text, slots)
    assert shown == "Drug X [SLOT 1] IL-6 and [SLOT 1] TNF in [SLOT 2]."
    assert "reduce" not in shown and "mice" not in shown


@pytest.mark.parametrize(("kind", "claim", "answer", "differ"), [
    ("direction", "increases", "decreased", True),
    ("direction", "inhibits", "up-regulated", True),
    ("direction", "increases", "elevated", False),
    ("direction", "reduces", "had no measurable effect on", False),  # no polarity: not comparable
    ("population", "patients", "rats", True),
    ("population", "patients", "kidney transplant recipients", False),
    ("population", "in vivo", "mice", False),
    ("population", "in vivo", "in vitro", True),
    ("population", "mice", "in vivo", False),
    ("population", "humans", "tissue samples", False),  # names no population
    ("relation", "justifies", "provides the rationale for", False),
    ("relation", "justifies", "was associated with", True),
    ("relation", "requires", "improves", True),
    ("relation", "causes", "increases", False),  # a stated effect is causal
    ("relation", "causes", "is correlated with", True),
    ("relation", "requires", "is essential for", False),
    ("relation", "causes", "not stated", False),
])
def test_differs(kind: str, claim: str, answer: str, differ: bool) -> None:
    assert differs(_slot(kind, claim), answer) is differ


def test_short_stems_match_whole_words_only() -> None:
    assert not differs(_slot("population", "patients"), "ratio of treated grafts")
    assert not differs(_slot("population", "patients"), "pigment cells were counted")


@pytest.mark.parametrize("answer", ["", "not stated", "Not reported in the passages", "n/a"])
def test_not_stated(answer: str) -> None:
    assert not_stated(answer)


def test_element_names_the_kind_and_the_claim_words() -> None:
    slots = find_slots(CLAIM)
    assert element_for(slots[2]) == "population: 'reduces graft loss in patients'"
    assert element_for(slots[1]).startswith("direction of effect: '")
