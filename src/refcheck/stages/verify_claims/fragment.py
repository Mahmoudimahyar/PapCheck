"""Fragment / anaphoric cited spans (V5.7 #7): no dispute softening, no clearing to supported.

"Combining both features (Doe et al., 2020)." asserts nothing a source can check: its
referent is in an earlier sentence. On the V4.9 gold set the blind cross-check
resolved such an anaphor its own way, found trivial support, the dispute rule softened a
correct not_supported to partial, and only the dispute hold kept the element adjudicator
from showing "supported". So for a fragment span:

* a disputed negative keeps the verifier's verdict (dispute.disputed_verdict
  ``fragment``), also in the mirrored unusual-positive dispute;
* an adjudicator / co-cited union clearing cannot turn the partial into "supported"
  (``hold_fragment``: the partial is kept with a note and a review flag).

A span is a fragment when citation detection marked the sentence a fragment
(claim_quality, detect_citations/claim_quality.py), or when the cited span is short
and opens with an anaphor ("These ...", "Combining these ..."); a list or example span
("such as X", "both in vitro and in vivo") names its own content and is not one. Figure-credit lines
("Adapted from ...") are fragments by design and keep their own rules (credit.py).
Off with REFCHECK_V57_DISABLE=7 (v57.py).
"""

import re
from typing import TYPE_CHECKING

from refcheck.stages.verify_claims import v57
from refcheck.stages.verify_claims.credit import figure_credit
from refcheck.stages.verify_claims.layers import cited_for
from refcheck.stages.verify_claims.outcome_rules import apply_outcome_rules
from refcheck.stages.verify_claims.verifier_helpers import PairContext

if TYPE_CHECKING:
    from refcheck.stages.verify_claims.cascade import CascadeOutcome

MAX_ANAPHOR_WORDS = 6
_ANAPHOR = re.compile(
    r"^(?:(?:combining|integrating|leveraging|using|with|of|all|together)\s+)?"
    r"(?:these|this|those|such\b(?!\s+as\b)|both\b(?!.*\band\b))\b", re.IGNORECASE)
FRAGMENT_NOTE = ("Fragment: referent not in the cited span (the citing text points back to "
                 "an earlier sentence), so the verdict is not softened or cleared; please "
                 "check what this citation is meant to support.")
_ELEMENT_NOTE = "Element check: '"


def anaphoric(span: str) -> bool:
    """A short span that opens with an anaphor ("These approaches", "Combining this")."""
    words = span.split()
    return 0 < len(words) <= MAX_ANAPHOR_WORDS and bool(_ANAPHOR.match(" ".join(words)))


def fragment_span(ctx: PairContext) -> bool:
    """The cited span is a fragment or a short anaphoric span (module doc)."""
    if figure_credit(ctx):
        return False
    if getattr(ctx.claim, "claim_quality", "ok") == "fragment":
        return True
    return anaphoric(cited_for(ctx.claim, ctx.claim_text) or ctx.claim_text)


def fragment_rule(ctx: PairContext) -> bool:
    """#7 applies to this pair (on, and a fragment span)."""
    return v57.enabled(7) and fragment_span(ctx)


def hold_fragment(ctx: PairContext, before: "CascadeOutcome",
                  after: "CascadeOutcome") -> "CascadeOutcome":
    """``after`` (adjudicated), or the routed partial kept when a clearing made a
    fragment span "supported" (the adjudication is recorded as held)."""
    if (before.verdict != "partially_supported" or after.verdict != "supported"
            or not fragment_rule(ctx)):
        return after
    summary = after.adjudication
    if summary is not None and summary.outcome == "cleared":
        summary = summary.model_copy(update={"outcome": "held"})
    cleared = [n for n in after.notes if n.startswith(_ELEMENT_NOTE) and n not in before.notes]
    held = before.model_copy(update={
        "layer_path": after.layer_path, "layers": after.layers, "adjudication": summary,
        "notes": [*before.notes, *cleared, FRAGMENT_NOTE], "needs_review": True})
    return apply_outcome_rules(ctx, held)
