"""Turn a CascadeOutcome into a VerificationResult and apply the POST rules.

POST (spec §0): contradicted -> needs review; negative finals need a
validated closest/contradicts quote or a "missing" note, else review;
abstract-only + not_supported -> cannot_verify (abstract_insufficient)
unless a validated contradicts quote exists; numeric mismatch between claim
and quoted numbers -> note + review (never changes the verdict). V5.2: claim
numbers found nowhere in the source -> note + review; a supporting quote that
itself cites other work -> "secondary citation" note (post_checks.py; V5.6: not when
the paper states the point itself, own_statement.py).
V5.4: a quoted-number mismatch is waived for a figure stated right around a
quote (another arm / cohort of the quoted result), not for one stated elsewhere
in the paper; partial sub-type fields + one note per guard (partial_fields.py).
"""

from refcheck.models.verification import ModelReasoning, VerificationResult, VoteRecord
from refcheck.stages.verify_claims.calibration import ScreenThresholds
from refcheck.stages.verify_claims.cascade import CascadeOutcome
from refcheck.stages.verify_claims.gates import numeric_mismatch
from refcheck.stages.verify_claims.layer_quotes import dedupe_contained_texts
from refcheck.stages.verify_claims.layers import (
    NEGATIVE,
    POSITIVE,
    LayerResult,
    axis_of,
    cited_for,
    pack_for,
)
from refcheck.stages.verify_claims.partial_fields import partial_fields
from refcheck.stages.verify_claims.post_checks import (
    missing_numbers_note,
    quote_surroundings,
    searchable_text,
    secondary_citation_note,
)
from refcheck.stages.verify_claims.screen import ScreenResult
from refcheck.stages.verify_claims.verifier_converters import (
    LAYER_TIER,
    evidence_sections_for,
    layer_reasoning,
    layer_vote,
    screen_reasoning,
    screen_vote,
)
from refcheck.stages.verify_claims.verifier_helpers import (
    PairContext,
    apply_claim_type_behavior,
    dedupe_quotes,
)

ABSTRACT_CONFIDENCE_CAP = 0.60
DISAGREEMENT_CONFIDENCE_CAP = 0.70
_MAX_EVIDENCE_QUOTES = 5


def _trace(screen: ScreenResult | None, out: CascadeOutcome, thresholds: ScreenThresholds,
           ) -> tuple[list[ModelReasoning], list[VoteRecord]]:
    reasoning = [layer_reasoning(layer) for layer in out.layers]
    votes = [layer_vote(layer) for layer in out.layers]
    if screen is not None and screen.ok:
        reasoning.insert(0, screen_reasoning(screen, out.clear_eligible, out.failed_gates,
                                             thresholds))
        votes.insert(0, screen_vote(screen, out.clear_eligible))
    return reasoning, votes


def _supporting_layers(out: CascadeOutcome) -> list[LayerResult]:
    """Label layer first, then other layers on the same positive/negative axis."""
    label = out.label_layer
    if label is None:
        return []
    others = [lay for lay in out.layers if lay is not label and lay.axis is not None
              and lay.axis == label.axis]
    return [label, *others]


def _quotes_validated(label: LayerResult | None) -> bool | None:
    if label is None or label.output is None or not label.output.quotes:
        return None
    return not label.invalid_quotes


def build_result(ctx: PairContext, screen: ScreenResult | None, out: CascadeOutcome,
                 thresholds: ScreenThresholds, latency_ms: int) -> VerificationResult:
    """VerificationResult for a sourced pair, POST rules applied."""
    reasoning_trace, votes = _trace(screen, out, thresholds)
    layers = _supporting_layers(out)
    # V5.6 (E6): a quote contained in another layer's longer quote is dropped too.
    quotes = dedupe_contained_texts(
        dedupe_quotes([q.text for lay in layers for q in lay.validated_quotes], []))
    label = out.label_layer
    # Passage ids are only meaningful within the pack a layer saw (standard vs expanded).
    cited = [q.passage_id for lay in layers if label is not None
             and lay.pack_kind == label.pack_kind for q in lay.validated_quotes]
    pack = pack_for(ctx, label.pack_kind) if label is not None else ctx.pack
    # The adjudicator re-reads the elements of a partial; it is not another opinion.
    decisive = [lay.axis for lay in out.layers if lay.axis is not None
                and lay.role != "adjudicator"]
    final_axis = axis_of(out.verdict)
    result = VerificationResult(
        claim_id=ctx.claim.id, reference_id=ctx.ref.id, source_coverage=ctx.coverage,
        verdict="cannot_verify", tier=out.tier, final_tier=out.tier,
        decided_by=out.decided_by, consensus_type=out.consensus_type,
        layer_path=list(out.layer_path),
        escalation_path=sorted({LAYER_TIER[p] for p in out.layer_path if p in LAYER_TIER}),
        model_reasoning=reasoning_trace, votes=votes, total_models_consulted=len(votes),
        agreement_ratio=round(decisive.count(final_axis) / len(decisive), 3)
        if decisive and final_axis else 0.0,
        screen_p_support=screen.s if screen else None,
        screen_p_contradict=screen.probs.get("finding_conflicts") if screen else None,
        screen_p_topic=screen.probs.get("topic_match") if screen else None,
        cost_usd=round((screen.cost_usd if screen else 0.0)
                       + sum(lay.cost_usd for lay in out.layers), 6),
        latency_ms=latency_ms, quotes_validated=_quotes_validated(label),
        evidence_quotes=quotes[:_MAX_EVIDENCE_QUOTES],
        evidence_sections=evidence_sections_for(pack, quotes, cited, ctx.claim_text),
        text_quality_score=ctx.doc.quality_score,
        section_relevance="abstract" if ctx.coverage == "abstract_only" else "high",
        needs_user_review=out.needs_review,
    )
    if out.verdict not in POSITIVE and out.verdict not in NEGATIVE:
        return _cannot_verify(result, out, label)
    return _post_rules(ctx, result, out, label)


def _cannot_verify(result: VerificationResult, out: CascadeOutcome,
                   label: LayerResult | None) -> VerificationResult:
    if out.cv_reason == "llm_error":
        text = f"Verification failed (LLM/API error): {out.error}"
    elif label is not None and label.output is not None:
        text = label.output.explanation + (f" Missing: {label.output.missing}"
                                           if label.output.missing else "")
    else:
        text = "The source passages do not contain enough information to decide."
    return result.model_copy(update={"verdict": "cannot_verify", "confidence": 0.0,
                                     "reasoning": text.strip(),
                                     "cannot_verify_reason": out.cv_reason})


def _post_rules(ctx: PairContext, result: VerificationResult, out: CascadeOutcome,
                label: LayerResult | None) -> VerificationResult:
    if label is None or label.output is None:  # cannot happen for routed finals
        return _cannot_verify(result, out, label)
    output = label.output
    notes = list(out.notes)
    review = result.needs_user_review
    confidence = output.confidence
    if review and out.consensus_type in ("disputed", "verifier_unconfirmed"):
        confidence = min(confidence, DISAGREEMENT_CONFIDENCE_CAP)
    if ctx.coverage == "abstract_only":
        confidence = min(confidence, ABSTRACT_CONFIDENCE_CAP)
        if out.verdict == "not_supported" and not label.quotes("contradicts"):
            text = output.explanation + " Only the abstract was available; the full text " \
                "may contain the finding."
            return result.model_copy(update={
                "verdict": "cannot_verify", "confidence": 0.0, "reasoning": text,
                "cannot_verify_reason": "abstract_insufficient"})
    if out.verdict == "contradicted":
        review = True
    if out.verdict in NEGATIVE and not label.quotes("closest", "contradicts") \
            and not output.missing:
        review = True
        notes.append("No validated source quote backs this negative verdict.")
    if out.verdict in POSITIVE and not label.quotes("supports"):
        review = True
        notes.append("No supporting quote could be validated against the source.")
    # Only the part this reference is cited for: other clauses belong to other references.
    # A figure stated right around a quote (not anywhere in the paper) is not a mismatch.
    part = cited_for(ctx.claim, ctx.claim_text) or ctx.claim_text
    absent = missing_numbers_note(ctx)
    mismatch = numeric_mismatch(part, result.evidence_quotes,
                                quote_surroundings(ctx, _supporting_layers(out)))
    if mismatch is not None:
        review = True
        notes.append(f"Numbers in the claim ({', '.join(mismatch[0])}) do not appear in the "
                     f"quoted evidence ({', '.join(mismatch[1])}); please check.")
    if absent is not None:
        review = True
        notes.append(absent)
    secondary = secondary_citation_note(
        [q for lay in _supporting_layers(out) for q in lay.validated_quotes], ctx=ctx)
    if secondary is not None:
        notes.append(secondary)
    fields = partial_fields(out.verdict, label, out.layers, ctx.coverage, out.guards,
                            claim_part=part, source_text=searchable_text(ctx.doc),
                            recheck_cleared=out.recheck_cleared)
    notes.extend(fields.notes)
    text = output.explanation + (f" Missing: {output.missing}" if output.missing
                                 and out.verdict in NEGATIVE else "")
    final = result.model_copy(update={
        "verdict": out.verdict, "confidence": round(confidence, 3),
        "reasoning": " ".join([text.strip(), *notes]).strip(), "needs_user_review": review,
        **fields.result_update(),
    })
    return apply_claim_type_behavior(final, ctx.claim)
