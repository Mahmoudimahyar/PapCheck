"""Which verdict to show when the blind cross-check disputes a NEGATIVE verifier verdict.

Before V5.2 a dispute kept the verifier's (harsher) verdict. On the V4.9
manuscript 36/40 "not supported" flags were such disputes and the manual
review sided with the cross-check in ~28 of them: whether a source partially
or does not support a claim is a severity call on which models (and people)
often disagree. The rule below was chosen by offline replay
(scripts/eval/replay_policy.py, recorded runs only): agreement with the manual
review 5/40 -> 26/40; 6-way accuracy Citation-Integrity cascade 47.3% -> 47.3%,
SciFact cascade 61.0% -> 60.5%, Citation-Integrity paired haiku x luna 46.9% ->
48.5%; binary problem precision/recall unchanged on all three ("show the
cross-check's verdict" reached 29/40 but lost ~3 points of problem recall).
When the cross-check found support:

* ``not_supported`` -> ``partially_supported`` (never plain "supported" from a dispute
  after the element adjudicator clears every element: adjudicate_apply.py; the
  exceptions are the credit line below and V5.7 #4: the co-cited union check releases
  a disputed pair to "supported" when EVERY element was cleared with an exact quote,
  each about the element (adjudicate_result.released); the dispute note and review
  flag stay);
* ``not_relevant`` -> ``not_supported`` (another model found on-topic support, so
  "unrelated source" overstates it; the recorded benchmarks do not support
  going further);
* ``contradicted`` -> kept (an opposite finding is categorical; softening it lost
  accuracy in every replay).

Exception: a figure/table credit line ("Adapted from X et al.") whose legend panel
text could not be found only claims provenance (credit.provenance_only) and the
figure itself cannot be read, so a verifier "not relevant" there is usually a
category error; when the cross-check finds the depicted work with a validated quote,
its verdict is shown (still reviewed; not under the strict policy). V5.6: a credit
whose panel text was found is judged on that text like any claim (normal rule).

The same one-step rule is mirrored for an unusual POSITIVE whose cross-check is
negative (escalation.cross_check_positive), except after an evidence re-check
overturned a negative verdict (two of three runs negative: shown unsoftened).

V5.7 #7: a fragment / anaphoric cited span (fragment.py) is never softened: the
cross-check resolved a referent the cited span does not contain.

V5.8 #20 (F1, ``screen_tie_break``; EXPERIMENTAL, off unless REFCHECK_V57_ENABLE=20): a
``not_supported`` verifier verdict whose cross-check says "supported" WITH a validated
supporting quote, while the recorded fast screen rated the finding stated
(finding_stated >= TIE_STATED) and on topic (topic_match >= TIE_TOPIC), is shown as
supported: two of three signals found support. The "disputed" consensus, the review flag
and both views stay. Never for ``not_relevant`` (the one-step rule above applies), a
fragment span, the strict policy, a cross-check without a validated quote, or without a
screen (G1: a degraded screen disables it). Offline gold replay: over-harsh -2, both TEST
pairs (thresholds read off the 4 TEST disputes whose cross-check said supported, 0 DEV
hits), so it is not held out and stays opt-in until DEV evidence exists.

A cross-check that cannot decide (insufficient_evidence) or is itself negative
leaves the verifier's verdict. Every dispute stays in the review queue and the
result records both views.

Live check (Citation-Integrity test, 305 pairs, V5.3 rubric): problem recall
0.911 (strict rule 0.928) with 12 instead of 30 "not supported/not relevant"
verdicts on citations the gold labels as supported or partial.
REFCHECK_DISPUTE_POLICY=strict restores the old behaviour (keep the verifier's
verdict on every dispute) for users who prefer maximum sensitivity.
"""

import logging
import os
from typing import TYPE_CHECKING

from refcheck.llm import same_family
from refcheck.llm.model_lookup import spec_for
from refcheck.stages.verify_claims import v57
from refcheck.stages.verify_claims.credit import is_credit_line, provenance_only
from refcheck.stages.verify_claims.layers import POSITIVE

if TYPE_CHECKING:
    from refcheck.stages.verify_claims.layers import LayerResult
    from refcheck.stages.verify_claims.screen import ScreenResult
    from refcheck.stages.verify_claims.verifier_helpers import PairContext

__all__ = ["STEP_DOWN", "credit_line", "dispute_note", "dispute_policy", "disputed_verdict",
           "is_credit_line", "negative_shown", "screen_tie_break", "tie_note"]

logger = logging.getLogger(__name__)
_VIEW_CHARS = 240

# One severity step toward a positive cross-check (never past partially_supported).
STEP_DOWN: dict[str, str] = {
    "not_supported": "partially_supported",
    "not_relevant": "not_supported",
}


def dispute_policy() -> str:
    """"soften" (default) or "strict" (env REFCHECK_DISPUTE_POLICY)."""
    value = os.getenv("REFCHECK_DISPUTE_POLICY", "soften").strip().lower()
    if value not in ("soften", "strict"):
        logger.warning("Unknown REFCHECK_DISPUTE_POLICY=%r; using 'soften'", value)
        return "soften"
    return value


def credit_line(ctx: "PairContext", confirm: "LayerResult") -> bool:
    """Provenance-only credit whose cross-check found the depicted work with a validated quote.

    A credit WITH legend panel text (credit.py) is a substantive claim about the panel:
    the normal one-step softening applies.
    """
    return provenance_only(ctx) and bool(confirm.quotes("supports"))


def unconfirmed_verdict(verifier: str, fragment: bool = False) -> str:
    """V5.8 #34: verdict shown when the cross-check could not run (error, outage, budget cap).

    A verifier's first not_supported matched the gold label in 2 of 33 pairs (25 were
    partial), so without a second opinion it is shown one step milder and reviewed;
    contradicted and fragment spans are kept; the strict policy keeps the verifier's verdict.
    """
    if dispute_policy() == "strict" or fragment or not v57.enabled(34):
        return verifier
    return STEP_DOWN.get(verifier, verifier)


def unconfirmed_note(error: str | None, what: str, verifier: str, shown: str) -> str:
    """Note for a pair whose cross-check failed (and the softened verdict, if any)."""
    note = f"The cross-check call failed ({error}); {what}"
    if shown != verifier:
        note += (f" Shown as {shown} (the verifier said {verifier}): without a second opinion a"
                 " single model's verdict is shown one step milder and queued for review.")
    return note


def disputed_verdict(verifier: str, confirm: str | None, credit: bool = False,
                     fragment: bool = False) -> str:
    """Verdict shown when ``confirm`` disputes the verifier's negative ``verifier`` verdict.

    ``credit``: provenance-only credit line with a quoted positive cross-check;
    ``fragment``: a fragment / anaphoric span (fragment.fragment_rule): never softened.
    """
    if confirm not in POSITIVE or dispute_policy() == "strict" or fragment:
        return verifier
    return (confirm or verifier) if credit else STEP_DOWN.get(verifier, verifier)


TIE_STATED = 0.7
TIE_TOPIC = 0.8


def screen_tie_break(verifier: str, confirm: str | None, probs: dict[str, float] | None,
                     fragment: bool = False, quoted: bool = False) -> bool:
    """V5.8 #20 (module doc): the screen breaks a not_supported-vs-supported dispute whose
    cross-check has a validated supporting quote (``quoted``)."""
    found = probs or {}
    return (v57.enabled(20) and bool(found) and quoted and not fragment
            and confirm == "supported" and verifier == "not_supported"
            and dispute_policy() != "strict"
            and found.get("finding_stated", 0.0) >= TIE_STATED
            and found.get("topic_match", 0.0) >= TIE_TOPIC)


def negative_shown(verifier: str, confirm: "LayerResult", credit: bool, fragment: bool,
                   screen: "ScreenResult | None") -> tuple[str, list[str]]:
    """The verdict shown for a disputed negative and the tie-break note, if it applied."""
    probs = screen.probs if screen is not None else {}
    if screen_tie_break(verifier, confirm.verdict, probs, fragment,
                        quoted=bool(confirm.quotes("supports"))):
        return "supported", [tie_note(probs)]
    return disputed_verdict(verifier, confirm.verdict, credit, fragment=fragment), []


def tie_note(probs: dict[str, float]) -> str:
    return (f"Screen tie-break: the fast screen rated the finding stated "
            f"({probs.get('finding_stated', 0.0):.2f}) and on topic "
            f"({probs.get('topic_match', 0.0):.2f}), siding with the cross-check; shown as "
            "supported, please check.")


def _view(layer: "LayerResult") -> str:
    """One layer's own reason, shortened, for the dispute note."""
    if layer.output is None:
        return ""
    text = " ".join((layer.output.missing or layer.output.explanation).split())
    return text if len(text) <= _VIEW_CHARS else text[:_VIEW_CHARS].rsplit(" ", 1)[0] + " …"


def who(l2: "LayerResult", confirm: "LayerResult") -> str:
    """Who cross-checked: another family, or the V5.8 same-family fallback (OpenAI outage)."""
    if l2.model_id and confirm.model_id and same_family(spec_for(l2.model_id),
                                                        spec_for(confirm.model_id)):
        return "a second model of the same family (degraded cross-check)"
    return "an independent model from another family"


def dispute_note(l2: "LayerResult", confirm: "LayerResult", shown: str) -> str:
    """Both views of a disputed negative, so the reviewer sees what each model said."""
    head = f"Disputed: the verifier said {l2.verdict} but {who(l2, confirm)} said {confirm.verdict}"
    head += "." if shown == l2.verdict else f"; shown as {shown} pending review."
    views = [f"Verifier: {v}" for v in [_view(l2)] if v]
    views += [f"Cross-check: {v}" for v in [_view(confirm)] if v]
    return " ".join([head, *views])
