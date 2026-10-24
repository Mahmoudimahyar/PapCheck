"""Claim slots of the blind slot probe (V5.7 #15): find, mask, compare. No LLM.

A verifier can waive a relation, an effect direction or a population in its prose
("close paraphrase") and list no element, so nothing checks it. The probe
(slot_probe.py; CoVe / QAGS style) masks these words of the cited span ("[SLOT 1]"),
asks the source what fills each slot WITHOUT showing the claim's word, and compares:

* relation   justify / require / necessitate / cause / lead to / result in / enable /
             depend on; agrees when the answer shares a stem or a synonym group (a
             causal claim also accepts a stated effect: "increases");
* direction  increase / reduce / promote / inhibit / up- / down-regulate ...; differs
             only on the opposite polarity;
* population patients / humans / mice / rats / in vivo / in vitro ...; differs only
             when the answer names another population ("in vivo" matches any human or
             animal one, never "in vitro").

At most one slot per kind (its first occurrence; every occurrence of that word is
masked). An answer that is "not stated", or names nothing comparable, never differs.
"""

import re
from typing import Literal

from pydantic import BaseModel

SlotKind = Literal["relation", "direction", "population"]
KIND_LABEL: dict[str, str] = {"relation": "relation", "direction": "direction of effect",
                              "population": "population"}
KIND_TYPE: dict[str, str] = {"relation": "unsupported_inference",
                             "direction": "specific_detail_mismatch",
                             "population": "scope_overgeneralized"}
WINDOW_WORDS = 4  # claim words kept on each side of a slot in the element text

_PATTERNS: dict[str, re.Pattern[str]] = {
    "relation": re.compile(
        r"(?<![-\w])(?:justif(?:y|ies|ied|ying|ication)|requir(?:e|es|ed|ing|ement)"
        r"|necessit(?:y|ate|ates|ated)|caus(?:e|es|ed|ing)|lead(?:s|ing)?\s+to|led\s+to"
        r"|result(?:s|ed|ing)?\s+in|enabl(?:e|es|ed|ing)|depend(?:s|ed|ent)?\s+on)\b",
        re.IGNORECASE),
    "direction": re.compile(
        r"(?<![-\w])(?:increas|decreas|reduc|elevat|rais|enhanc|improv|augment|attenuat"
        r"|diminish|worsen|accelerat|promot|activat|induc|stimulat|suppress|prevent|impair"
        r"|abolish|up-?regulat|down-?regulat)(?:s|e|es|ed|ing|ion|ment|ement)?\b"
        r"|(?<![-\w])(?:inhibit(?:s|ed|ing|ion)?|block(?:s|ed|ing|ade)?|lower(?:s|ed|ing))\b",
        re.IGNORECASE),
    "population": re.compile(
        r"\b(?:patients?|humans?|volunteers|children|adults|recipients|participants|mice"
        r"|mouse|murine|rats?|pigs?|porcine|swine|primates?|monkeys?|macaques?|dogs?|canine"
        r"|rabbits?|sheep|ovine|zebrafish|in\s+vivo|in\s+vitro)\b", re.IGNORECASE),
}
_UP = ("increas", "elevat", "raise", "enhanc", "improv", "augment", "accelerat", "promot",
       "activat", "induc", "stimulat", "upregulat", "up-regulat", "boost", "higher", "more$")
_DOWN = ("decreas", "reduc", "attenuat", "diminish", "worsen", "suppress", "prevent",
         "impair", "abolish", "inhibit", "block", "lower", "downregulat", "down-regulat",
         "less$", "fewer", "loss$")
_RELATION_GROUPS: tuple[tuple[str, ...], ...] = (
    ("caus", "lead$", "led$", "result", "induc", "drive", "trigger", "produc", "respons"),
    ("requir", "necess", "need$", "needed", "essential", "depend", "indispens", "prerequisit"),
    ("justif", "support", "warrant", "motivat", "rational", "basis", "favor", "favour", "argue"),
    ("enabl", "allow", "permit", "facilitat", "possib"),
)
_POPULATION_GROUPS: tuple[tuple[str, ...], ...] = (
    ("patient", "human", "volunteer", "child", "adult", "recipient", "participant",
     "subject", "people", "clinical", "individual", "men$", "women"),
    ("mice$", "mouse", "murine"), ("rat$",), ("pig$", "porcine", "swine", "minipig"),
    ("primate", "monkey", "macaque", "nhp$", "baboon"), ("dog$", "canine"), ("rabbit",),
    ("sheep", "ovine"), ("zebrafish",), ("in vivo",), ("in vitro", "cultur", "cell line"),
)
_IN_VIVO = 9  # index of ("in vivo",): every group before it is a living population
_NOT_STATED = re.compile(r"^\W*(?:not\s+(?:stated|reported|mentioned|given|specified)"
                         r"|unknown|unclear|none|n/?a)\b", re.IGNORECASE)


class Slot(BaseModel):
    """One masked word of the cited span."""

    number: int
    kind: SlotKind
    text: str  # the claim's words, as written
    window: str  # the claim words around it (element text)


def _window(text: str, start: int, end: int) -> str:
    before = text[:start].split()[-WINDOW_WORDS:]
    after = text[end:].split()[:WINDOW_WORDS]
    return " ".join([*before, text[start:end], *after]).strip(" ,;.")


def find_slots(text: str) -> list[Slot]:
    """The first relation / direction / population word of ``text`` (module doc)."""
    found: list[tuple[int, str, re.Match[str]]] = []
    for kind, pattern in _PATTERNS.items():
        match = pattern.search(text)
        if match is not None:
            found.append((match.start(), kind, match))
    found.sort(key=lambda item: item[0])
    return [Slot(number=i, kind=kind, text=m.group(0),  # type: ignore[arg-type]
                 window=_window(text, m.start(), m.end()))
            for i, (_, kind, m) in enumerate(found, start=1)]


def masked(text: str, slots: list[Slot]) -> str:
    """``text`` with every occurrence of each slot's words replaced by "[SLOT n]"."""
    for slot in slots:
        pattern = re.compile(rf"(?<![\w-]){re.escape(slot.text)}(?![\w-])", re.IGNORECASE)
        text = pattern.sub(f"[SLOT {slot.number}]", text)
    return text


def _has(low: str, stem: str) -> bool:
    """A word starting with ``stem``; "rat$" is a whole word ("rat", "rats"; never "rate")."""
    word = stem.removesuffix("$")
    tail = r"s?(?![a-z])" if stem.endswith("$") else ""
    return re.search(rf"(?<![a-z]){re.escape(word)}{tail}", low) is not None


def _groups(text: str, groups: tuple[tuple[str, ...], ...]) -> set[int]:
    low = text.lower()
    return {i for i, group in enumerate(groups) if any(_has(low, stem) for stem in group)}


def _population(text: str) -> set[int]:
    """Population groups; "in vivo" matches any human or animal group."""
    groups = _groups(text, _POPULATION_GROUPS)
    return groups | set(range(_IN_VIVO)) if _IN_VIVO in groups else groups


def _polarity(text: str) -> set[str]:
    low = text.lower()
    found = {"up" for stem in _UP if _has(low, stem)}
    return found | {"down" for stem in _DOWN if _has(low, stem)}


def not_stated(answer: str) -> bool:
    """The probe found nothing for the slot."""
    return not answer.strip() or _NOT_STATED.search(answer) is not None


def differs(slot: Slot, answer: str) -> bool:
    """The source's answer differs from the claim's slot words (module doc)."""
    if not_stated(answer):
        return False
    if slot.kind == "direction":
        claim, source = _polarity(slot.text), _polarity(answer)
        return bool(claim) and bool(source) and not claim & source
    if slot.kind == "population":
        source_groups = _population(answer)
        return bool(source_groups) and not _population(slot.text) & source_groups
    claim_groups = _groups(slot.text, _RELATION_GROUPS)
    if claim_groups & _groups(answer, _RELATION_GROUPS) or slot.text.lower()[:5] in answer.lower():
        return False
    return not (0 in claim_groups and _polarity(answer))  # a stated effect is causal


def element_for(slot: Slot) -> str:
    """The adjudicator element for a slot the source answers differently."""
    return f"{KIND_LABEL[slot.kind]}: '{slot.window}'"
