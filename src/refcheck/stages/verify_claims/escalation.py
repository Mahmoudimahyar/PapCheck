"""Second opinions for the V5.1 cascade: blind cross-family checks and the judge.

The cascade (cascade.py) lets the cheap verifier decide. These helpers run when
its verdict is not trusted on its own:

* a NEGATIVE verdict -> ``cross_check_negative`` (agree = confirmed; disagree = disputed,
  reviewed, shown one step toward the cross-check: dispute.py, incl. credit lines and #20;
  cross-check unavailable = shown one step milder too, reviewed: V5.8 #34);
* an UNUSUAL POSITIVE (no validated supports quote, a screen conflict / topic mismatch, a
  "supported" still listing elements, or a re-check that overturned a negative) ->
  ``cross_check_positive``: a problem found by the other family is shown one step milder
  (unsoftened after an overturn), disputed, reviewed. ``judge_positive``: older, costlier.
  V5.7: never upgrades a partial to supported (#8); no fragment softening (#7).
"""

from typing import TYPE_CHECKING, Protocol

from refcheck.llm import resolve_role, same_family
from refcheck.llm.model_lookup import spec_for
from refcheck.llm.roles import role_candidates
from refcheck.models.verification import DecidedBy
from refcheck.stages.verify_claims import v57
from refcheck.stages.verify_claims.dispute import (
    credit_line,
    dispute_note,
    disputed_verdict,
    negative_shown,
    unconfirmed_note,
    unconfirmed_verdict,
    who,
)
from refcheck.stages.verify_claims.fragment import FRAGMENT_NOTE, fragment_rule
from refcheck.stages.verify_claims.layers import LayerResult, axis_of, pack_for
from refcheck.stages.verify_claims.partial_fields import uncovered_elements
from refcheck.stages.verify_claims.recheck import overturn_note
from refcheck.stages.verify_claims.retriever import EvidencePack
from refcheck.stages.verify_claims.verifier_helpers import PairContext

if TYPE_CHECKING:
    from refcheck.llm import Role
    from refcheck.stages.verify_claims.cascade import CascadeOutcome


class CascadeRun(Protocol):
    """The parts of the cascade's per-pair run object these helpers use."""

    ctx: PairContext

    async def layer(self, role: "Role", layer: str, pack: EvidencePack, expanded: bool,
                    model: str | None = None) -> LayerResult: ...

    async def expanded(self) -> EvidencePack: ...

    def final(self, label: LayerResult | None, verdict: str, decided_by: DecidedBy,
              consensus: str, tier: int, **extra: object) -> "CascadeOutcome": ...


def families_match(a: LayerResult, b: LayerResult) -> bool:
    """True when two layers' models come from the same model family."""
    if not a.model_id or not b.model_id:
        return a.provider == b.provider
    return same_family(spec_for(a.model_id), spec_for(b.model_id))


def confirm_model(first: LayerResult) -> str | None:
    """A confirm model from a DIFFERENT family than ``first`` (blind cross-check).

    None = no other-family candidate is available; the role's normal resolution
    is used and the result is marked as a same-family check.
    """
    if not first.model_id:
        return None
    family = spec_for(first.model_id)
    same = [c.id for c in role_candidates("confirm") if same_family(c, family)]
    other = resolve_role("confirm", exclude=same)
    return other.id if other is not None else None


def l2_pack(ctx: PairContext, l2: LayerResult) -> EvidencePack:
    """The pack the deciding verifier saw (expanded / re-check pack if it was re-run)."""
    return pack_for(ctx, l2.pack_kind)


async def _confirm(run: CascadeRun, l2: LayerResult) -> LayerResult:
    return await run.layer("confirm", "confirm", l2_pack(run.ctx, l2), expanded=False,
                           model=confirm_model(l2))


def _unconfirmed(run: CascadeRun, l2: LayerResult, confirm: LayerResult,
                 what: str) -> "CascadeOutcome":
    shown = unconfirmed_verdict(l2.verdict or "", fragment_rule(run.ctx))
    return run.final(l2, shown, "verifier", "verifier_unconfirmed", 2, needs_review=True,
                     notes=[unconfirmed_note(confirm.error, what, l2.verdict or "", shown)])


async def cross_check_negative(run: CascadeRun, l2: LayerResult) -> "CascadeOutcome":
    """Blind cross-family check of a negative verdict (same evidence pack)."""
    confirm = await _confirm(run, l2)
    if confirm.output is None:
        return _unconfirmed(run, l2, confirm, "this flag was not independently confirmed.")
    if confirm.axis == "negative":
        if families_match(l2, confirm):
            return run.final(l2, l2.verdict or "", "verifier", "confirmed", 2, needs_review=True,
                             notes=["Confirmed by a model of the same family only."])
        return run.final(l2, l2.verdict or "", "verifier", "confirmed", 2,
                         notes=["Confirmed by a second model family."])
    fragment = fragment_rule(run.ctx)
    shown, tie = negative_shown(l2.verdict or "", confirm, credit_line(run.ctx, confirm),
                                fragment, getattr(run, "screen", None))
    # A positive shown verdict is explained (and its quotes validated) by the cross-check.
    label = confirm if axis_of(shown) == "positive" else l2
    notes = [dispute_note(l2, confirm, shown), *([FRAGMENT_NOTE] if fragment else []), *tie]
    return run.final(label, shown, "verifier", "disputed", 2, needs_review=True, notes=notes)


def unusual_why(l2: LayerResult) -> str:
    """What made a positive verifier verdict unusual (cascade.verifier_final)."""
    if not l2.quotes("supports"):
        return "the verifier gave no supporting quote that could be found in the source"
    if l2.verdict == "supported" and (elements := uncovered_elements(l2.output)):
        shown = "; ".join(f"'{e}'" for e in elements)
        return f"the verifier still listed elements it did not find in the source ({shown})"
    return "the fast screen flagged a possible conflict or topic mismatch"


async def cross_check_positive(run: CascadeRun, l2: LayerResult, why: str | None = None,
                               soften: bool = True) -> "CascadeOutcome":
    """Unusual positive: the cross-check decides whether a problem is shown.

    ``why``: what made it unusual. ``soften``: dispute.py's rule, mirrored (off after overturns).
    """
    why = why or unusual_why(l2)
    confirm = await _confirm(run, l2)
    if confirm.output is None:
        return _unconfirmed(run, l2, confirm, f"review needed because {why}.")
    if confirm.axis == "negative":
        note = (f"Disputed: the verifier said {l2.verdict}, but {why} and "
                f"{who(l2, confirm)} said {confirm.verdict}.")
        if l2.verdict == "partially_supported":
            # The verifier already reports a problem; partial vs. not supported is a
            # severity call (low human agreement), so keep it and let a human decide.
            return run.final(l2, l2.verdict, "verifier", "disputed", 2, needs_review=True,
                             notes=[note])
        fragment = fragment_rule(run.ctx)
        shown = (disputed_verdict(confirm.verdict or "", l2.verdict, fragment=fragment)
                 if soften else confirm.verdict)
        notes = [f"{dispute_note(l2, confirm, shown or '')} Unusual because {why}.",
                 *([FRAGMENT_NOTE] if fragment else [])]
        return run.final(confirm, shown or "", "verifier", "disputed", 2, needs_review=True,
                         notes=notes)
    if l2.verdict == "supported" and confirm.verdict == "partially_supported":
        # The unusual "supported" and the cross-check both point at a problem: show it.
        note = f"{dispute_note(l2, confirm, confirm.verdict)} Unusual because {why}."
        return run.final(confirm, confirm.verdict, "verifier", "disputed", 2,
                         needs_review=True, notes=[note])
    upgrade = (confirm.axis == "positive" and bool(confirm.quotes("supports"))
               and not l2.quotes("supports"))
    # V5.7 #8: a "supported" cross-check never upgrades a partial verifier verdict.
    keep = (upgrade and l2.verdict != "supported" and confirm.verdict == "supported"
            and v57.enabled(8))
    label = confirm if upgrade and not keep else l2
    note = (f"Both models found support, but {why}; please check." if confirm.axis == "positive"
            else f"The cross-check could not decide from the evidence, and {why}; please check.")
    if keep:
        note = (f"The cross-check found support, but {why}, and a cross-check never upgrades "
                "the verifier's partially supported verdict; please check.")
    return run.final(label, label.verdict or "", "verifier", "confirmed", 2, needs_review=True,
                     notes=[note])


async def cross_check_overturn(run: CascadeRun, first: LayerResult,
                               second: LayerResult) -> "CascadeOutcome":
    """The evidence re-check overturned a negative (or contradicted-by-quote) verdict.

    Never final on the re-run alone: cross-checked like an unusual positive, unsoftened as
    two of three runs were negative (always reviewed); the first run's contradicting quote
    stays in the notes, and the evidence_recheck guard only when a positive verdict is shown.
    """
    why = f"the evidence re-check overturned the first verdict ({first.verdict})"
    out = await cross_check_positive(run, second, why=why, soften=False)
    guards = out.guards if axis_of(out.verdict) == "positive" else []
    return out.model_copy(update={"notes": [*out.notes, overturn_note(first)],
                                  "guards": guards})


async def judge_positive(run: CascadeRun, l2: LayerResult) -> "CascadeOutcome":
    """Opt-in (REFCHECK_JUDGE_UNUSUAL_POSITIVES=1): strong judge on the expanded pack."""
    judge = await run.layer("judge", "judge", await run.expanded(), expanded=True)
    if judge.output is None:
        return run.final(l2, l2.verdict or "", "verifier", "verifier_unconfirmed", 2,
                         needs_review=True,
                         notes=[f"Escalation to the judge failed ({judge.error})."])
    if judge.axis is None:
        reason = ("insufficient_in_source" if run.ctx.coverage == "full_text"
                  else "abstract_insufficient")
        return run.final(judge, "cannot_verify", "judge", "judge", 3, cv_reason=reason)
    review = judge.axis != l2.axis
    notes = [f"Verifier said {l2.verdict}; the judge said {judge.verdict}."] if review else []
    return run.final(judge, judge.verdict or "", "judge", "judge", 3, needs_review=review,
                     notes=notes)
