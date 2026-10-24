"""Credit-panel rubric after the element adjudicator (V5.7 #6).

A figure credit judged on its legend panel (credit.py, V5.6) is checked with claim-level
strictness, but a legend describes an IMAGE: time-point labels ("POD 41"), colour keys
("green / red"), arrows or insets are printed in the figure, not in the source's text,
and legends routinely drop a hedge ("potentially") of the text. On the gold set and the
app run such survivors made 7 attributions partial that reviewers called supported.
After the adjudicator, on a credit judged on panel text only, a surviving element that is

* visual-only: the adjudicator found it "absent" (never "contradicted": a source that
  states another value is a mismatch) and it names a figure key ("colour coding",
  "green/red", arrows, insets), a colour or a time-point label ("POD 41") that the
  source text never states (the key phrase, the colour word; a label only when the text
  states NO time point of that kind: "POD 170" in the text makes "POD 41" a mismatch,
  not an image-only detail) -> category "panel_visual": note "not checkable from text -
  check the source figure";
* an overstated hedge: category "overstated", no number, and the adjudicator's note
  says the SOURCE hedges it ("the source suggests", "only as a potential mechanism";
  a bare "may" in the note is not enough) -> category "panel_hedge": note only (a
  weaker RESULT, e.g. "no efficacy shown, its potential is being assessed", stays);

is cleared with that note (never a guard) and the pair is flagged for review. Every
other survivor is untouched. Off with REFCHECK_V57_DISABLE=6.
"""

import re

from refcheck.stages.verify_claims import v57
from refcheck.stages.verify_claims.adjudicate import Adjudication
from refcheck.stages.verify_claims.adjudicate_rules import ElementDecision
from refcheck.stages.verify_claims.credit import panel_of
from refcheck.stages.verify_claims.post_checks import searchable_text
from refcheck.stages.verify_claims.verifier_helpers import PairContext

PANEL_CATEGORIES = frozenset({"panel_visual", "panel_hedge"})
VISUAL_NOTE = "a figure detail not checkable from the source text - check the source figure"
HEDGE_NOTE = "a hedge dropped by the figure legend, not a different finding"
_C = (r"(?:red|green|blue|yellow|orange|purple|violet|pink|magenta|cyan|black|white|gr[ae]y"
      r"|brown)")
# A figure key: "colour coding", "green/red", arrows, insets (absent from the text as such).
_KEY = re.compile(rf"\bcolou?r[- ]?(?:cod\w*|key|scheme|map\w*)|\bpseudo-?colou?r\w*"
                  rf"|\b{_C}\s*(?:/|and|vs\.?)\s*{_C}\b|\b(?:arrow(?:head)?s?|asterisks?|insets?"
                  rf"|dashed|dotted)\b", re.IGNORECASE)
_COLOUR = re.compile(rf"\b{_C}\b", re.IGNORECASE)  # a single colour word
# A time-point label ("POD 41", "day 41", "41 post-operative days"): its number.
_TIME_LABEL = re.compile(
    r"\bPOD\s*-?(?P<a>\d+)|\b(?P<b>\d+)\s*(?:post-?operative|post-?transplant\w*)\s+days?\b"
    r"|\b(?:post-?operative\s+)?days?\s*(?P<c>\d+)\b", re.IGNORECASE)
_TENTATIVE = r"(?:potential|possible|putative|hypothetical|speculative|tentative)"
_WHO = r"\b(?:source|authors?|study|paper|text)\s+(?:only\s+|merely\s+)?"
# The note says the SOURCE hedges ("the source only suggests", "only as a potential X").
_HEDGE_NOTE = re.compile(
    rf"\b(?:only|merely)\s+(?:as\s+)?(?:an?\s+)?{_TENTATIVE}\b|\bhedg\w*"
    rf"|{_WHO}(?:suggest|speculat|hypothesi[sz]|propos|presum)\w*"
    rf"|{_WHO}(?:says?|calls?|describes?|presents?|frames?|treats?)\s+(?:\S+\s+){{0,4}}?"
    rf"as\s+(?:an?\s+)?{_TENTATIVE}\b", re.IGNORECASE)


def credit_on_panel(ctx: PairContext) -> bool:
    """A figure credit judged on its legend panel text."""
    return bool(ctx.credit_panel) or panel_of(ctx.claim) is not None


def _in_text(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.IGNORECASE) is not None


def _label_stated(number: str, text: str) -> bool:
    n = re.escape(number)
    return _in_text(rf"\b(?:POD|days?|d)\s*-?{n}\b|\b{n}\s*(?:post-?operative\s+|post-?"
                    rf"transplant\w*\s+)?days?\b", text)


def visual_only(element: str, source_text: str) -> bool:
    """``element`` names a figure detail whose tokens the source text never states (a
    time-point label: the text states no time point of that kind at all)."""
    keys = [m.group(0) for m in _KEY.finditer(element)]
    colours = [m.group(0) for m in _COLOUR.finditer(element)] if not keys else []
    labels = [next(g for g in m.groups() if g) for m in _TIME_LABEL.finditer(element)]
    other_label = _TIME_LABEL.search(source_text) is not None
    stated = [*(_in_text(re.escape(k), source_text) for k in keys),
              *(_in_text(rf"\b{re.escape(c)}\b", source_text) for c in colours),
              *(other_label or _label_stated(n, source_text) for n in labels)]
    return bool(stated) and not any(stated)


def _category(d: ElementDecision, source_text: str) -> str | None:
    if d.category == "absent" and visual_only(d.element, source_text):
        return "panel_visual"
    if d.category == "overstated" and not re.search(r"\d", d.element) \
            and _HEDGE_NOTE.search(d.note):
        return "panel_hedge"
    return None


def credit_rubric(ctx: PairContext, adj: Adjudication) -> Adjudication:
    """``adj`` with the panel-only survivors cleared as panel_* (module doc)."""
    if not v57.enabled(6) or not adj.ok or not adj.surviving or not credit_on_panel(ctx):
        return adj
    text = searchable_text(ctx.doc)
    decisions = []
    for d in adj.decisions:
        category = None if d.cleared or d.category == "rule" else _category(d, text)
        if category is None:
            decisions.append(d)
            continue
        note = VISUAL_NOTE if category == "panel_visual" else HEDGE_NOTE
        decisions.append(d.model_copy(update={"category": category, "cleared": True,
                                              "note": f"{note} ({d.note})" if d.note else note}))
    return adj.model_copy(update={"decisions": decisions})


def panel_cleared(adj: Adjudication) -> bool:
    """The rubric cleared at least one element (the pair goes to review)."""
    return any(d.category in PANEL_CATEGORIES for d in adj.cleared)
