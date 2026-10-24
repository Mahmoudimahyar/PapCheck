"""Build results API items and summary from stored verification results."""

from collections import Counter
from pathlib import Path

from refcheck.api.routes.results_schemas import (
    ClaimDetail,
    ModelReasoningItem,
    PartialFields,
    ResultItem,
    ResultsSummary,
    VoteSummary,
)
from refcheck.api.routes.results_trace import (
    CONFIRMATION_LABELS,
    confirmation_status,
    layer_names,
    screen_p_problem,
)
from refcheck.llm import degradation
from refcheck.models.claim import Claim
from refcheck.models.verification import VerificationResult
from refcheck.stages.generate_report.claim_signals import claim_signals
from refcheck.stages.generate_report.partial_findings import (
    action_of,
    elements_of,
    guard_counts,
    guarded_results,
    guards_of,
    partial_counts,
    partial_type_of,
    severity_counts,
    severity_of,
)
from refcheck.stages.generate_report.result_signals import result_signals

_VERDICTS = (
    "supported", "partially_supported", "not_supported", "contradicted",
    "cannot_verify", "not_relevant",
)
# Pipeline order, so the notices read the way the run went (unknown roles last).
_ROLE_ORDER = ("screen", "embedding", "verifier", "confirm", "judge", "utility")


def degraded_notices(session_dir: Path | None) -> list[str]:
    """V5.8: one sentence per LLM role that ran degraded, then each fix once.

    Read from the notes pipeline_runner saves next to the session (the DOCX report's
    "Degraded mode" section); [] without a session dir (an id that is not a session
    folder), when the run had none or the file is unreadable.
    """
    if session_dir is None:
        return []
    saved = degradation.load(session_dir / degradation.RUN_FILE).values()
    items = sorted(saved, key=lambda d: _ROLE_ORDER.index(d.role)
                   if d.role in _ROLE_ORDER else len(_ROLE_ORDER))
    # Several roles usually share one cause (e.g. no OpenAI credits): say the fix once.
    lines = [degradation.describe(d.model_copy(update={"action": None})) for d in items]
    actions = [d.action for d in items if d.action]
    return lines + list(dict.fromkeys(actions))


def build_summary(verifications: list[VerificationResult],
                  session_dir: Path | None = None) -> ResultsSummary:
    """Verdict counts, how pairs were decided, review count, total cost and, given the
    session's directory, the run's degraded-mode notices."""
    counts: dict[str, int] = dict.fromkeys(_VERDICTS, 0)
    for v in verifications:
        if v.verdict in counts:
            counts[v.verdict] += 1
    return ResultsSummary(
        total=len(verifications), **counts,
        decided_by=dict(Counter(v.decided_by for v in verifications)),
        needs_review=sum(1 for v in verifications if v.needs_user_review),
        total_cost_usd=round(sum(v.cost_usd for v in verifications), 6),
        partial_types=partial_counts(verifications),
        partial_severity=severity_counts(verifications),
        guarded=len(guarded_results(verifications)),
        guards=guard_counts(verifications),
        degraded_notices=degraded_notices(session_dir),
    )


def _claim_detail(claim: Claim | None) -> ClaimDetail:
    if claim is None:
        return ClaimDetail()
    signals = claim_signals(claim)
    return ClaimDetail(
        manuscript_text=claim.manuscript_text, extracted_claim=claim.extracted_claim,
        claim_type=claim.claim_type, priority=claim.priority,
        cited_for=signals.cited_for, claim_quality=claim.claim_quality,
        mapping_ambiguous=claim.mapping_ambiguous,
        candidate_reference_ids=list(claim.candidate_reference_ids),
        mapping_note=signals.mapping_text,
        citation_markers=list(claim.location.citation_markers) if claim.location else [],
    )


def _reasoning_items(v: VerificationResult) -> list[ModelReasoningItem]:
    return [ModelReasoningItem(
        layer=layer, model_name=mr.model_name, model_display=mr.model_display,
        verdict=mr.verdict, confidence=mr.confidence,
        reasoning=mr.reasoning, evidence_quotes=mr.evidence_quotes,
        response_time_ms=mr.response_time_ms,
        input_tokens=mr.input_tokens, output_tokens=mr.output_tokens,
        source_section_preview=mr.source_section_preview,
    ) for layer, mr in zip(layer_names(v), v.model_reasoning, strict=True)]


def build_item(v: VerificationResult, claim: Claim | None) -> ResultItem:
    """One results row: verdict, claim detail and the V5 layer trace."""
    confirmation = confirmation_status(v)
    return ResultItem(
        claim_id=v.claim_id, reference_id=v.reference_id,
        verdict=v.verdict, confidence=v.confidence,
        evidence_quotes=v.evidence_quotes, reasoning=v.reasoning,
        tier=v.tier, source_coverage=v.source_coverage,
        needs_user_review=v.needs_user_review,
        user_override=v.user_override,
        user_override_reason=v.user_override_reason,
        claim=_claim_detail(claim),
        consensus_type=v.consensus_type,
        final_tier=v.final_tier,
        total_models_consulted=v.total_models_consulted,
        agreement_ratio=v.agreement_ratio,
        model_reasoning=_reasoning_items(v),
        cannot_verify_reason=v.cannot_verify_reason,
        section_relevance=v.section_relevance,
        text_quality_score=v.text_quality_score,
        decided_by=v.decided_by,
        screen_p_support=v.screen_p_support,
        screen_p_problem=screen_p_problem(v),
        screen_p_contradict=v.screen_p_contradict,
        screen_p_topic=v.screen_p_topic,
        layer_path=v.layer_path,
        escalation_path=v.escalation_path,
        votes=[VoteSummary.model_validate(vote.model_dump()) for vote in v.votes],
        cost_usd=v.cost_usd,
        latency_ms=v.latency_ms,
        quotes_validated=v.quotes_validated,
        confirmation=confirmation,
        confirmation_label=CONFIRMATION_LABELS[confirmation],
        signals=result_signals(v),
        **partial_fields(v).model_dump(),
    )


def partial_fields(v: VerificationResult) -> PartialFields:
    """V5.4 sub-type fields, with the taxonomy defaults filled in when not stored.

    Empty when a reviewer changed the verdict: they explained the model's verdict.
    """
    return PartialFields(
        partial_type=partial_type_of(v), partial_severity=severity_of(v),
        author_action=action_of(v), unsupported_elements=elements_of(v),
        guards_applied=guards_of(v),
    )


def build_items(
    verifications: list[VerificationResult], claims_by_id: dict[int, Claim],
) -> list[ResultItem]:
    """Result items with claim detail, in input order."""
    return [build_item(v, claims_by_id.get(v.claim_id)) for v in verifications]
