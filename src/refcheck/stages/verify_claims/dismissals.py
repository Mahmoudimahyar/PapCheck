"""No clearance without a quote (V5.6, finding L2): audit a layer's "dismissed" list.

The manual review of "supported" verdicts found guards that waved real gaps through:
"wording only" cleared a scope change or an added "every year", "author framing"
cleared an agenda attributed to the sources, and "co-cited share" assumed another
reference stated an element. Each concern a layer clears now names its element,
guard, passage id and a verbatim quote, and code checks it with the element
adjudicator's quote rules (clear_rules.py), for every guard:

* the quote has >= MIN_QUOTE_WORDS words and is found EXACTLY (after normalisation)
  in this source's passages, never front matter (title / author block / header); for
  cocited_share exactly in a co-cited reference's abstract shown in the prompt (not
  its title). A fuzzy match is not enough: "did prolong" scores ~0.9 against a source
  saying "did not prolong";
* a guard that says the element IS stated (cocited_share, secondary_source) needs a
  quote about the element that keeps its figures (``clear_rules.states_element``);
* wording / framing / secondary_source may never clear an element
  ``clear_rules.disqualifier`` rejects (time frame, mechanism, recommendation,
  population, frequency, number): a secondary report is not this paper's statement
  of a specific (V5.7 #3: for wording / framing only a disqualifying phrase their
  quote does not state counts; secondary_source stays quote-blind);
* cocited_share is "not needed" when THIS source states the element: an exact quote
  of this source about the element, or a validated evidence quote whose TEXT states
  it (the model's own ``states`` label is not trusted). The clearance stands, but no
  guard and no "move the citation" note is recorded.

Only validated dismissals produce benign notes (and so guards); an invalid one makes
its element an unsupported element, so the usual routing (cross-check / re-check /
adjudicator) gets a chance with its own quote rules.
"""

from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from refcheck.models.verification import Dismissal, JudgeOutput
from refcheck.stages.verify_claims.clear_rules import (
    EXACT,
    disqualifier,
    long_enough,
    states_element,
)
from refcheck.stages.verify_claims.layer_quotes import ValidatedQuote, validate_quote
from refcheck.stages.verify_claims.quote_context import front_matter, is_title
from refcheck.stages.verify_claims.quote_validator import validate_quotes
from refcheck.stages.verify_claims.retriever import EvidencePack
from refcheck.stages.verify_claims.verifier_helpers import PairContext

WORDING_GUARDS = frozenset({"author_framing_or_example", "overliteral_wording"})
# Guards whose element may never be one clear_rules.disqualifier names.
NO_SPECIFICS_GUARDS = WORDING_GUARDS | {"secondary_source"}
NOTE_ORDER = ("cocited_share", "author_framing_or_example", "overliteral_wording",
              "secondary_source")
_SAME_ELEMENT = 80  # token_set_ratio, as recheck.is_listed
_MAX_ELEMENTS = 5


class DismissalAudit(BaseModel):
    """The audited output and one trace line per rejected dismissal."""

    output: JudgeOutput
    rejected: list[str] = Field(default_factory=list)


def _same(a: str, b: str) -> bool:
    return fuzz.token_set_ratio(a.lower(), b.lower()) >= _SAME_ELEMENT


def in_source(d: Dismissal, pack: EvidencePack, ctx: PairContext) -> bool:
    """The quote is long enough, exactly in this source's passages, not front matter."""
    if not long_enough(d.quote) or validate_quote(d.passage_id, d.quote, "supports", pack,
                                                  EXACT) is None:
        return False
    return front_matter(d.quote, ctx.ref, ctx.doc) is None


def in_cocited(d: Dismissal, ctx: PairContext) -> bool:
    """The quote is long enough and exactly in a co-cited abstract shown (not a title)."""
    if not long_enough(d.quote):
        return False
    return any(r.abstract and not (r.title and is_title(d.quote, r.title))
               and validate_quotes([d.quote], r.abstract, EXACT)[0].found_in_source
               for r in ctx.co_cited)


def stated_here(element: str, evidence: list[ValidatedQuote]) -> bool:
    """A validated evidence quote of this source states ``element`` (its text, not its
    ``states`` label)."""
    return any(q.role == "supports" and not q.context and states_element(element, q.text)
               for q in evidence)


def _cocited_share(d: Dismissal, pack: EvidencePack, ctx: PairContext,
                   evidence: list[ValidatedQuote]) -> str:
    if stated_here(d.element, evidence) or (
            states_element(d.element, d.quote) and in_source(d, pack, ctx)):
        return "not_needed"
    if not states_element(d.element, d.quote):
        return "its quote does not state the element"
    return "valid" if in_cocited(d, ctx) else "its quote is not in a co-cited abstract shown"


def check(d: Dismissal, pack: EvidencePack, ctx: PairContext,
          evidence: list[ValidatedQuote]) -> str:
    """"valid", "not_needed" (cocited_share for an element this source states) or why not."""
    if not d.element.strip():
        return "it names no element"
    if d.guard == "cocited_share":
        return _cocited_share(d, pack, ctx, evidence)
    # V5.7 #3: wording / framing are judged on their quote; a secondary report never clears
    quote = d.quote if d.guard in WORDING_GUARDS else None
    if d.guard in NO_SPECIFICS_GUARDS and (why := disqualifier(d.element, quote)) is not None:
        what = "wording or framing" if d.guard in WORDING_GUARDS else "a secondary report"
        return f"it names {why}, which {what} cannot clear"
    if d.guard == "secondary_source" and not states_element(d.element, d.quote):
        return "its quote does not state the element"
    if not long_enough(d.quote):
        return "its quote is too short to check"
    return "valid" if in_source(d, pack, ctx) else "its quote is not in this source's passages"


def audit_dismissals(out: JudgeOutput, pack: EvidencePack, ctx: PairContext,
                     evidence: list[ValidatedQuote]) -> DismissalAudit:
    """``out`` with only validated dismissals, benign notes derived from them, and the
    elements of rejected dismissals added to ``unsupported_elements``."""
    kept: list[Dismissal] = []
    notes: set[str] = set()
    elements = list(out.unsupported_elements)
    rejected: list[str] = []
    for d in out.dismissed:
        verdict = check(d, pack, ctx, evidence)
        if verdict in ("valid", "not_needed"):
            kept.append(d)
            if verdict == "valid":
                notes.add(d.guard)
            continue
        rejected.append(f"'{d.element}' ({d.guard}): {verdict}")
        if d.element.strip() and not any(_same(d.element, e) for e in elements):
            elements.append(d.element.strip()[:160])
    output = out.model_copy(update={
        "dismissed": kept, "benign_notes": [n for n in NOTE_ORDER if n in notes],
        "unsupported_elements": elements[:_MAX_ELEMENTS]})
    return DismissalAudit(output=output, rejected=rejected)
