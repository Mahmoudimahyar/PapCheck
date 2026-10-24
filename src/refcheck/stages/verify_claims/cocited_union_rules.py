"""Clearing rule of the co-cited union check (used by cocited_union.py).

The model's "cocited" is NOT trusted on its own. An element is cleared only when:

* the answer names a co-cited passage that was shown ("R12-P3"; the "R<number>-"
  prefix picks the reference);
* its quote has >= MIN_QUOTE_WORDS words and is found EXACTLY (after normalisation,
  as for the adjudicator's stated / cocited categories), on whole words, inside ONE
  of THAT reference's passages (the named one or, a harmless id mix-up within one
  paper, another passage of the same reference). A quote spliced across two
  passages or starting / stopping mid-word never counts; nor does a quote from
  another co-cited reference or from this reference's own source;
* the quote is about the element: more than half of the element's content words
  (bm25.tokenize: stopwords dropped, light stemming) are in the quote, so a generic
  sentence that happens to be in the paper ("in the present study and") clears
  nothing; V5.7 #5: for a quote found exactly, clear_rules.about_loose also accepts
  it (abbreviations expanded from that reference's passages, meta words dropped,
  >= 40% of the content words);
* an element with a number keeps every number in the quote, and one with a
  frequency / universality quantifier keeps that word (a source stating
  "some patients" does not clear "in all patients");
* the quote is not that reference's title or page-1 header (V5.6: front matter
  identifies a paper, it states nothing it found).

V5.8 (round2_rules.py): #25 the about-check also accepts one disjunct or an initialism
(``about_parts``); #21 a quote not found is retried once without edge function words.
cocited_union_apply also clears author-framing scaffolds (#23) and near-duplicates of an
element the adjudicator cleared (#24); ``rule`` records which.

``about_element`` / ``figures_kept`` live in clear_rules.py (shared with the verifier's
dismissal audit) and are re-exported here.
"""

import re

from pydantic import BaseModel

from refcheck.models.adjudication import CocitedCheck
from refcheck.stages.verify_claims import v57
from refcheck.stages.verify_claims.clear_rules import (
    MIN_QUOTE_WORDS,
    about_element,
    figures_kept,
)
from refcheck.stages.verify_claims.cocited_union_pack import UnionSource
from refcheck.stages.verify_claims.quote_context import is_title
from refcheck.stages.verify_claims.quote_validator import normalize_for_match, validate_quotes
from refcheck.stages.verify_claims.round2_rules import about_parts, edge_trimmed

__all__ = ["UnionDecision", "about_element", "decide_union", "figures_kept", "front_matter_of",
           "quote_in_source", "source_of", "whole_words_in"]

_REF_PREFIX = re.compile(r"^\[?\s*R(?P<number>\d+)\s*-", re.IGNORECASE)
_HEADER_SIMILARITY = 0.95  # as quote_context.in_header
_QUOTE_EDGES = "\"'“”…."  # stripped from a quote's ends, as quote_validator does


class UnionDecision(BaseModel):
    """The code's decision for one element asked about."""

    element: str
    cleared: bool = False
    number: int | None = None  # the co-cited reference that states it
    passage_id: str | None = None
    quote: str | None = None
    note: str = ""
    rule: str = ""  # V5.8: "framing" (#23) / "twin" (#24) when a rule cleared it
    twin: str | None = None  # #24: the cleared element this one restates


def source_of(passage_id: str | None, sources: list[UnionSource]) -> UnionSource | None:
    """The shown co-cited reference a passage id ("R12-P3") belongs to."""
    match = _REF_PREFIX.match((passage_id or "").strip())
    if match is None:
        return None
    number = int(match.group("number"))
    return next((s for s in sources if s.number == number), None)


def whole_words_in(quote: str, text: str) -> bool:
    """``quote`` is in ``text`` after normalisation, neither end inside a word."""
    norm_quote = normalize_for_match(quote.strip().strip(_QUOTE_EDGES))[0].strip()
    if not norm_quote:
        return False
    head = r"(?<![^\W_])" if norm_quote[0].isalnum() else ""
    tail = r"(?![^\W_])" if norm_quote[-1].isalnum() else ""
    norm_text = normalize_for_match(text)[0]
    return re.search(head + re.escape(norm_quote) + tail, norm_text) is not None


def quote_in_source(source: UnionSource, quote: str) -> bool:
    """``quote`` on whole words inside one passage of ``source`` (never across two)."""
    return any(whole_words_in(quote, p.text) for p in source.pack.passages)


def front_matter_of(source: UnionSource, quote: str) -> bool:
    """``quote`` is the co-cited reference's title or is printed in its page-1 header."""
    if source.title and is_title(quote, source.title):
        return True
    return bool(source.header.strip()) and validate_quotes(
        [quote], source.header, _HEADER_SIMILARITY)[0].found_in_source


def decide_union(element: str, check: CocitedCheck | None,
                 sources: list[UnionSource]) -> UnionDecision:
    """The clearing rule (module doc), with #21's retry without edge function words."""
    found = _decide_union(element, check, sources)
    if found.cleared or check is None or not check.quote or not v57.enabled(21):
        return found
    trimmed = edge_trimmed(check.quote)
    if trimmed == check.quote:
        return found
    retry = _decide_union(element, check.model_copy(update={"quote": trimmed}), sources)
    return retry if retry.cleared else found


def _decide_union(element: str, check: CocitedCheck | None,
                  sources: list[UnionSource]) -> UnionDecision:
    """The clearing rule (module doc); never trusts the model's category alone."""
    if check is None:
        return UnionDecision(element=element, note="no answer for this element")
    base = UnionDecision(element=element, note=check.note, passage_id=check.passage_id)
    quote = check.quote
    if check.category != "cocited" or quote is None or len(quote.split()) < MIN_QUOTE_WORDS:
        return base
    source = source_of(check.passage_id, sources)
    if source is None or not figures_kept(element, quote):
        return base
    exact = quote_in_source(source, quote)
    if not about_element(element, quote) and not (exact and about_parts(
            element, quote, " ".join(p.text for p in source.pack.passages))):
        return base
    if front_matter_of(source, quote):
        return base.model_copy(update={"note": f"refused (title/header is not evidence): "
                                               f"{check.note}".strip()})
    cleared = exact
    return base.model_copy(update={"cleared": cleared, "quote": quote,
                                   "number": source.number if cleared else None})
