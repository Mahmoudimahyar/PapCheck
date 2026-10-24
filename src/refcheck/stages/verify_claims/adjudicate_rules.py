"""The element adjudicator's clearing rule and answer matching (used by adjudicate.py).

The model's category is NOT trusted on its own (``decide``). An element is cleared
only when its category is stated / cocited / framing / wording AND:

* stated / wording / framing: a verbatim quote of >= MIN_QUOTE_WORDS words is found
  EXACTLY (after normalisation: case, whitespace, ligatures, dashes, citation markers)
  in the pack the shown verdict was based on - for framing, the passage stating the
  factual core the framing wraps (V5.6: "author framing" cleared agendas attributed to
  the sources without one). A fuzzy match is not enough: one inverted or substituted
  key word ("increased" -> "decreased", a dropped "not", "rat" -> "human") still
  scores ~0.9 and would clear the element with text the source contradicts;
* cocited: the same exact match against a co-cited ABSTRACT shown (a title never clears);
* the quote is never front matter (quote_context.front_matter: this reference's title,
  author block or page-1 header; for cocited the co-cited reference's title): a title
  quote would otherwise become a stored "stated" evidence quote (V5.6, E1);
* framing / wording: the element has no disqualifier (clear_rules.disqualifier: a time
  frame, mechanism or cause, recommendation or need, population or model, frequency /
  universality word or number - each needs a passage that states it, V5.6; V5.7 #3:
  only one its clearing quote does not state), and framing gives a non-empty note;
* never an element a deterministic rule added ("lineage: ...", "number: ...",
  LOCKED_PREFIXES; outcome_rules.py): a model cannot check a publication year or a
  figure the source states differently.

V5.8 refinements (``decide``; round2_rules.py, framing_rules.py, each off with
REFCHECK_V57_DISABLE): #22 a "stated" answer its own note hedges is "overstated"; #27 an
"overstated" one without a trigger word is re-checked as wording; #21 a quote not found
is retried without edge function words; #23 an "absent" author-framing scaffold of the
cited span is cleared as framing.

Each answer is matched to an element by identity, never by position alone
(``match_checks``): a dropped, duplicated or reordered answer must not lend its
category to another element. An element without an answer survives.
"""

from collections.abc import Sequence
from typing import Protocol, TypeVar

from pydantic import BaseModel
from rapidfuzz import fuzz
from rapidfuzz.utils import default_process

from refcheck.models.adjudication import CLEARING_CATEGORIES, ElementCheck
from refcheck.stages.verify_claims import v57
from refcheck.stages.verify_claims.clear_rules import EXACT, MIN_QUOTE_WORDS, disqualifier
from refcheck.stages.verify_claims.framing_rules import FRAMING_NOTE, is_scaffold
from refcheck.stages.verify_claims.layer_quotes import ValidatedQuote, validate_quote
from refcheck.stages.verify_claims.quote_context import front_matter, is_title
from refcheck.stages.verify_claims.quote_validator import validate_quotes
from refcheck.stages.verify_claims.retriever import EvidencePack
from refcheck.stages.verify_claims.round2_rules import (
    edge_trimmed,
    hedged_stated,
    overstated_as_wording,
)
from refcheck.stages.verify_claims.verifier_helpers import PairContext

__all__ = ["EXACT", "LOCKED_PREFIXES", "MIN_QUOTE_WORDS", "ElementDecision", "cocited_quote_ok",
           "decide", "is_locked", "match_checks"]

FRONT_MATTER_NOTE = "refused (title/header is not evidence)"
_SAME_ELEMENT = 80  # token_set_ratio: a reworded element is still the same element
# Elements added by a deterministic rule (outcome_rules.py): never cleared by a model.
LOCKED_PREFIXES: tuple[str, ...] = ("lineage:", "number:", "colour key:")  # + figure_key (G2)


class _Answer(Protocol):
    @property
    def element(self) -> str: ...


AnswerT = TypeVar("AnswerT", bound=_Answer)


class ElementDecision(BaseModel):
    """The code's decision for one input element."""

    element: str
    category: str  # the model's category ("absent" when it gave no answer for this element)
    cleared: bool = False
    note: str = ""
    passage_id: str | None = None
    quote: str | None = None  # validated quote (stated / wording / cocited)
    validated: ValidatedQuote | None = None  # stated / wording: the quote as found in the pack


def _similarity(element: str, answer: str) -> tuple[float, float]:
    a, b = default_process(element), default_process(answer)
    return fuzz.token_set_ratio(a, b), fuzz.ratio(a, b)


def match_checks(elements: list[str], checks: Sequence[AnswerT]) -> list[AnswerT | None]:
    """The model's entry for each input element, or None (module doc; any answer model
    with an ``element``: the adjudicator's and the co-cited union check's).

    Pairs are taken best first: token-set similarity (>= _SAME_ELEMENT, the model
    may reword an element), then plain similarity, then the same position; each
    answer is used at most once.
    """
    pairs = [((*_similarity(e, c.element), i == j), i, j)
             for i, e in enumerate(elements) for j, c in enumerate(checks)]
    matched: list[AnswerT | None] = [None] * len(elements)
    used: set[int] = set()
    for score, i, j in sorted(pairs, key=lambda pair: pair[0], reverse=True):
        if score[0] >= _SAME_ELEMENT and matched[i] is None and j not in used:
            matched[i] = checks[j]
            used.add(j)
    return matched


def is_locked(element: str) -> bool:
    """An element a deterministic rule added (LOCKED_PREFIXES)."""
    return element.strip().lower().startswith(LOCKED_PREFIXES)


def _quote(check: ElementCheck) -> str | None:
    """The answer's quote when it is long enough to count."""
    quote = check.quote
    return quote if quote is not None and len(quote.split()) >= MIN_QUOTE_WORDS else None


def cocited_quote_ok(ctx: PairContext, quote: str) -> bool:
    """``quote`` is, exactly, in the abstract of a co-cited reference that was shown (and
    is not that reference's title)."""
    return any(r.abstract and not (r.title and is_title(quote, r.title))
               and validate_quotes([quote], r.abstract, EXACT)[0].found_in_source
               for r in ctx.co_cited)


def decide(element: str, check: ElementCheck | None, ctx: PairContext,
           pack: EvidencePack) -> ElementDecision:
    """The clearing rule with the V5.8 refinements (module doc; round2_rules.py,
    framing_rules.py): #22 a hedged "stated" is "overstated"; #27 an "overstated" without
    a trigger word is re-checked as wording; #21 a quote retried without edge function
    words; #23 an "absent" author-framing scaffold of the cited span is framing."""
    if check is not None and hedged_stated(check.category, check.note):
        check = check.model_copy(update={"category": "overstated"})
        found = _decide(element, check, ctx, pack)
    elif check is not None and overstated_as_wording(check.category, element, check.note):
        found = _decide(element, check.model_copy(update={"category": "wording"}), ctx, pack)
        found = found if found.cleared else _decide(element, check, ctx, pack)
    else:
        found = _decide(element, check, ctx, pack)
    if not found.cleared and check is not None and check.quote and v57.enabled(21) \
            and check.category in CLEARING_CATEGORIES \
            and (trimmed := edge_trimmed(check.quote)) != check.quote:
        retry = _decide(element, check.model_copy(update={"quote": trimmed}), ctx, pack)
        found = retry if retry.cleared else found
    cited = str(getattr(ctx.claim, "cited_for", "") or "") or ctx.claim_text
    if not found.cleared and is_scaffold(element, cited, found.category):
        return found.model_copy(update={"cleared": True, "category": "framing",
                                        "note": FRAMING_NOTE})
    return found


def _decide(element: str, check: ElementCheck | None, ctx: PairContext,
            pack: EvidencePack) -> ElementDecision:
    """The clearing rule (module doc); never trusts the model's category alone."""
    if is_locked(element):
        return ElementDecision(element=element, category="rule",
                               note="added by a deterministic check; never cleared")
    if check is None:
        return ElementDecision(element=element, category="absent",
                               note="no answer for this element")
    base = ElementDecision(element=element, category=check.category, note=check.note,
                           passage_id=check.passage_id)
    if check.category not in CLEARING_CATEGORIES:
        return base
    if check.category in ("framing", "wording") and (why := disqualifier(element, check.quote)):
        return base.model_copy(update={"note": f"refused ({why}): {check.note}"})
    if check.category == "framing" and not check.note.strip():
        return base
    if (quote := _quote(check)) is None:
        return base
    if check.category == "cocited":
        return base.model_copy(update={"cleared": cocited_quote_ok(ctx, quote), "quote": quote})
    found = validate_quote(check.passage_id or "", quote, "supports", pack, EXACT)
    if found is not None and front_matter(quote, ctx.ref, ctx.doc) is not None:
        return base.model_copy(update={"note": f"{FRONT_MATTER_NOTE}: {check.note}".strip()})
    return base.model_copy(update={"cleared": found is not None, "quote": quote,
                                   "validated": found})
