"""Post-routing "check first" triage of supported verdicts (V5.7 #9) and the slot probe (#15).

Called once per routed pair, after the element check and the deterministic rules
(cascade.run_cascade). A minority veto (Jain et al. 2025): one weak signal against a
"supported" verdict does not change it, it sends the pair to the review queue first.

1. the reasons (``check_first_reasons``): the screen rated finding_stated below
   SCREEN_STATED_MAX; every validated supports quote cites other work
   (post_checks.cites_other_work) or describes future / proposed work; the slot audit
   (V5.7 #2, slot_apply.py) fired but left the verdict supported; an evidence re-check
   overturned a partial / negative first run with no validated supports quote (V5.6 gold:
   all 12 flips with such a quote were right, both without one were missed partials);
   V5.8 #28 (F11, ``missing_named``): the deciding layer said supported but its own
   "missing" field names content no passage states ("No passage explicitly says ...";
   gold replay: 4 of 172 supported verdicts, 1 of them a gold partial);
2. a reason and REFCHECK_SLOT_PROBE=on: the blind slot probe (slot_probe.py) of the cited
   span's relation / direction / population words; it may make the pair partial;
3. still supported with a reason: the note (``check_first_note``, parsed by
   generate_report/result_signals.check_first) and a review flag. The verdict never
   changes here; REFCHECK_V57_DISABLE=9 drops the note and the flag.

Offline replay of the 281 gold pairs (V5.6 cached answers, $0): 30 of the 164 supported
verdicts flagged (dev 15/92, test 15/72) holding 5 of the 7 missed partials (6 with the
slot audit; precision 17-19% vs a 4.3% base); the review queue grows 84 -> 108 of 279.
"""

import re
from collections.abc import Iterable
from typing import TYPE_CHECKING

from refcheck.llm import CostTracker
from refcheck.stages.verify_claims.layers import LayerResult, cited_for
from refcheck.stages.verify_claims.post_checks import cites_other_work
from refcheck.stages.verify_claims.screen import ScreenResult
from refcheck.stages.verify_claims.slot_probe import probe_outcome, slot_probe_enabled
from refcheck.stages.verify_claims.slot_probe_rules import find_slots
from refcheck.stages.verify_claims.v57 import enabled
from refcheck.stages.verify_claims.verifier_helpers import PairContext

if TYPE_CHECKING:
    from refcheck.stages.verify_claims.cascade import CascadeOutcome

CHECK_FIRST_OPENING = "Check first:"  # pinned by result_signals.check_first
SCREEN_STATED_MAX = 0.3  # gold dev sweep: 0.25 catches 1 of 2 dev misses, 0.35 adds 3 FPs
SLOT_AUDIT_LAYER = "adjudicate_slots"  # slot_apply.SLOT_LAYER (V5.7 #2)
_FUTURE_MODAL = re.compile(
    r"\b(?:should be possible|future (?:work|studies|research)|remains to be|could potentially"
    r"|we propose|will be needed|warrant(?:s|ed)? further)\b", re.IGNORECASE)
_MISSING_NAMED = re.compile(r"\bno passage\b|\bnot explicitly\b"
                            r"|\bdo(?:es)? not (?:explicitly )?(?:state|say|mention|report)",
                            re.IGNORECASE)


def missing_named(label: LayerResult | None) -> bool:
    """V5.8 #28: the deciding layer's "missing" field names content no passage states."""
    out = label.output if label is not None else None
    return enabled(28) and out is not None and bool(out.missing) \
        and _MISSING_NAMED.search(out.missing or "") is not None


def secondary_only(label: LayerResult | None) -> bool:
    """Every validated supports quote cites other work or describes future / proposed
    work (at least one quote)."""
    quotes = label.quotes("supports") if label is not None else []
    return bool(quotes) and all(cites_other_work(q) or _FUTURE_MODAL.search(q.text)
                                for q in quotes)


def recheck_flip(layers: Iterable[LayerResult]) -> str | None:
    """The first run's verdict when the last evidence re-check turned a first run without
    a validated supports quote into supported."""
    shown = list(layers)
    first = next((lay for lay in shown if lay.layer == "verifier"), None)
    rerun = [lay for lay in shown if lay.layer == "verifier_recheck"]
    if first is None or first.verdict in (None, "supported") or first.quotes("supports"):
        return None
    return first.verdict if rerun and rerun[-1].verdict == "supported" else None


def slot_cleared(layers: Iterable[LayerResult]) -> str | None:
    """How the slot audit (V5.7 #2) that fired left the verdict ("was cleared" / "could not
    be checked"), None when it did not fire."""
    found = [lay for lay in layers if lay.layer == SLOT_AUDIT_LAYER]
    if not found:
        return None
    return "could not be checked" if found[-1].output is None else "was cleared"


def check_first_reasons(out: "CascadeOutcome", screen: ScreenResult | None) -> list[str]:
    """Why a supported outcome may hide a missed problem (module doc); [] otherwise."""
    if out.verdict != "supported":
        return []
    reasons: list[str] = []
    stated = screen.probs.get("finding_stated") if screen is not None and screen.ok else None
    if stated is not None and stated < SCREEN_STATED_MAX:
        reasons.append(f"the screen rated the finding unlikely to be stated ({stated:.2f})")
    if secondary_only(out.label_layer):
        reasons.append("every supporting quote cites other work or describes future work")
    if (slot := slot_cleared(out.layers)) is not None:
        reasons.append(f"a claim detail found nowhere in the source text {slot}")
    if missing_named(out.label_layer):
        reasons.append("the deciding check itself noted content no passage states")
    if (first := recheck_flip(out.layers)) is not None:
        reasons.append(f"an evidence re-check overturned a first '{first.replace('_', ' ')}' "
                       "verdict no source quote supported")
    return reasons


def check_first_note(reasons: list[str]) -> str:
    """The review note of a triaged supported verdict (parsed by result_signals)."""
    return (f"{CHECK_FIRST_OPENING} shown as supported, but {'; '.join(reasons)} — please "
            "confirm the source states every part of the claim.")


def with_check_first(out: "CascadeOutcome", reasons: list[str]) -> "CascadeOutcome":
    """``out`` with the check-first note and a review flag (a supported verdict only)."""
    if out.verdict != "supported" or not reasons or not enabled(9):
        return out
    note = check_first_note(reasons)
    if note in out.notes:
        return out
    return out.model_copy(update={"notes": [*out.notes, note], "needs_review": True})


async def check_first_outcome(ctx: PairContext, screen: ScreenResult | None,
                              out: "CascadeOutcome", tracker: CostTracker | None,
                              deadline: float) -> "CascadeOutcome":
    """The outcome after the triage and, when enabled, the slot probe (module doc)."""
    reasons = check_first_reasons(out, screen)
    if reasons and slot_probe_enabled():
        part = cited_for(ctx.claim, ctx.claim_text) or ctx.claim_text
        slots = find_slots(part)
        if slots:
            out = await probe_outcome(ctx, out, slots, part, tracker, deadline)
    return with_check_first(out, reasons)
