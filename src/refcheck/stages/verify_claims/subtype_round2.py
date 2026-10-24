"""V5.8 #26 (F14): sub-type refinements from the surviving elements' wording.

Applied by adjudicate_result.survivor_type after the type the survivors' categories
imply (typing only: no verdict, element or request changes). Each restates a taxonomy
v1.1 rule (prompts/partial_taxonomy.json):

* noun-phrase list (missing_element: "a list item; a named cell type, complication,
  factor ..."): every survivor is "absent" and a short noun phrase (<= NP_MAX_WORDS
  words, no relational / verb word, not a rule element "x: ...") -> an
  unsupported_inference becomes missing_element. Unrestricted all-absent ->
  missing_element on full text was rejected in V5.7 (dev 3 breaks / 1 fix);
* contradicted exclusivity / consequence: a specific_detail_mismatch whose
  "contradicted" survivors are only exclusivity words ("alone", "solely", "only") is
  certainty_overstated; if they are only consequences ("without ...", "thereby ...",
  "leading to ...") it is unsupported_inference (no specific is in question);
* quantifier -> scope (scope_overgeneralized (b): "adds a frequency, universality ...
  word"): a survivor carrying a frequency / universality quantifier that the source
  does not state ("overstated", "broadened" or "absent") turns certainty_overstated or
  missing_element into scope_overgeneralized.

Never on an abstract-only source (an all-absent partial there is coverage_limited by
design). Offline gold replay (snapshot, $0): type accuracy on flagged gold partials 49 -> 54 of
74 (dev 32 -> 33, test 17 -> 21), 0 broken. NOT held-out: 4 of the 5 gains are TEST
pairs whose errors informed the rules (dev served as the false-positive check). The dev
ablation credits the one DEV gain to the noun-phrase rule (#26, on; off with
REFCHECK_V57_DISABLE=26); the contradicted-exclusivity / consequence rule (#32) and the
quantifier rule (#33) have no DEV evidence and are opt-in (REFCHECK_V57_ENABLE=32,33).
"""

import re
from typing import TYPE_CHECKING

from refcheck.stages.verify_claims import v57

if TYPE_CHECKING:
    from refcheck.stages.verify_claims.adjudicate_rules import ElementDecision

NP_MAX_WORDS = 7
CONTRADICTED = 32  # sub-switch of #26: contradicted exclusivity / consequence
QUANTIFIER = 33  # sub-switch of #26: quantifier -> scope
_QUANT = re.compile(r"\b(often|frequently|commonly|usually|typically|generally|widely|most|all|"
                    r"always|universally|consistently|in general|many)\b", re.IGNORECASE)
_EXCL = re.compile(r"\b(alone|solely|sole|only|exclusively|entirely)\b", re.IGNORECASE)
_CONSEQ = re.compile(r"^(without|thereby|leading to|resulting in|which avoids|avoiding)\b",
                     re.IGNORECASE)
_VERBISH = re.compile(
    r"\b(cause\w*|lead\w*|result\w*|due|because|address\w*|circumvent\w*|bypass\w*|prompt\w*|"
    r"achiev\w*|lost|lose|limit\w*|promot\w*|enabl\w*|allow\w*|prevent\w*|reduc\w*|increas\w*|"
    r"improv\w*|compar\w*|than|by|through|via|is|are|was|were|be|been|can|may|do|does|did|will|"
    r"would|should|must)\b", re.IGNORECASE)
_QUANT_CATEGORIES = frozenset({"overstated", "broadened", "absent"})


def _noun_phrases(surviving: list["ElementDecision"]) -> bool:
    return all(d.category == "absent" and not _VERBISH.search(d.element)
               and len(d.element.split()) <= NP_MAX_WORDS and ":" not in d.element
               for d in surviving)


def _contradicted_type(surviving: list["ElementDecision"]) -> str | None:
    contra = [d.element for d in surviving if d.category == "contradicted"]
    if not contra or not all(_EXCL.search(e) or _CONSEQ.search(e) for e in contra):
        return None
    return "certainty_overstated" if all(_EXCL.search(e) for e in contra) \
        else "unsupported_inference"


def refined_type(ptype: str, surviving: list["ElementDecision"],
                 abstract_only: bool = False) -> str:
    """``ptype`` after the three rules (module doc), applied in order; never on an
    abstract-only source (its absent elements are reported as coverage_limited, V5.4)."""
    if not v57.enabled(26) or not surviving or abstract_only:
        return ptype
    if ptype == "unsupported_inference" and _noun_phrases(surviving):
        ptype = "missing_element"
    if ptype == "specific_detail_mismatch" and v57.enabled(CONTRADICTED):
        ptype = _contradicted_type(surviving) or ptype
    if (ptype in ("certainty_overstated", "missing_element") and v57.enabled(QUANTIFIER)
            and any(_QUANT.search(d.element) and d.category in _QUANT_CATEGORIES
                    for d in surviving)):
        ptype = "scope_overgeneralized"
    return ptype
