"""Claim-side slot audit of a final "supported" verdict: the trigger (V5.7 #2).

The verifier sometimes notices a claim slot the source does not state and waives it
in its explanation ("the 'every year' framing is a minor wording difference"),
returning supported with no element, so nothing downstream checks it. Here the cited
span's phrases of four slot classes (clear_rules.SLOT_PATTERNS: time frame, mechanism /
cause, recommendation / need, population / model; quantifiers excluded: they fired 7
false triggers for 1 true one on gold) are looked up in the WHOLE source text and the
validated quotes, with the class synonym lexicon (slot_lexicon.stated_in: "annually" ~
"per year", "cause" ~ "lead to" / "induce", "necessary" ~ "require"). A phrase found in
neither becomes an element ("time frame: 'every year'") for ONE element-adjudicator
call (slot_apply.py), which clears it only with an exact quote. Full-text sources only:
"stated nowhere" in an abstract only means "not in the abstract".

On the 281-pair gold set (offline, cached answers) the trigger fires on 2 gold-partial
"supported" pairs and on none of the gold-supported ones once the lexicon is applied.
Both true positives are TEST-split pairs and that count covers dev AND test, so it is
not a held-out estimate (the lexicon itself was fitted on dev false triggers only).
"""

from pydantic import BaseModel

from refcheck.stages.verify_claims.clear_rules import SLOT_PATTERNS
from refcheck.stages.verify_claims.slot_lexicon import stated_in
from refcheck.stages.verify_claims.slot_polarity import polarity_pairs

MAX_SLOTS = 4
# A surviving slot's partial type (the most severe survivor wins, adjudicate_result rank).
SLOT_TYPE: dict[str, str] = {
    "time frame": "specific_detail_mismatch", "mechanism": "unsupported_inference",
    "recommendation": "unsupported_inference", "population": "scope_overgeneralized",
    "polarity": "unsupported_inference"}  # V5.8 #31 (slot_polarity.py)


class SlotPhrase(BaseModel):
    """One cited-span phrase of a slot class the source states nowhere."""

    slot: str
    phrase: str
    against: str = ""  # polarity: the supporting quote's negated phrase ("not widely used")

    @property
    def element(self) -> str:
        return f"{self.slot}: '{self.phrase}'"

    @property
    def partial_type(self) -> str:
        return SLOT_TYPE[self.slot]


def slot_phrases(cited: str, source_text: str, quotes: list[str]) -> list[SlotPhrase]:
    """The cited span's slot phrases stated neither in the source nor in the quotes."""
    haystack = "\n".join([source_text, *quotes])
    found: list[SlotPhrase] = []
    seen: set[str] = set()
    for slot, pattern in SLOT_PATTERNS.items():
        for match in pattern.finditer(cited or ""):
            phrase = " ".join(match.group(0).split())
            if phrase.lower() in seen:
                continue
            seen.add(phrase.lower())
            if not stated_in(phrase, haystack):
                found.append(SlotPhrase(slot=slot, phrase=phrase))
    return found[:MAX_SLOTS]


def polarity_slots(cited: str, supports: list[str]) -> list[SlotPhrase]:
    """V5.8 #31: cited-span phrases a supporting quote negates (slot_polarity.py)."""
    return [SlotPhrase(slot="polarity", phrase=phrase, against=against)
            for phrase, against in polarity_pairs(cited, supports)]
