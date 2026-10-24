"""Helper functions for report preview and diff endpoints."""

from refcheck.models.claim import Claim
from refcheck.models.reference import Reference
from refcheck.models.verification import VerificationResult
from refcheck.stages.generate_report.claim_signals import narrowed_cited_for
from refcheck.stages.generate_report.partial_findings import (
    action_of,
    elements_of,
    partial_type_of,
    severity_of,
    type_label,
)
from refcheck.stages.generate_report.result_signals import check_first


def _finding(v: VerificationResult, claim: Claim | None) -> dict[str, str]:
    """Preview row: the claim, the clause this reference is cited for, dispute flag,
    and the V5.4 partial sub-type with what the author should do."""
    return {
        "claim_id": str(v.claim_id), "reference_id": str(v.reference_id),
        "verdict": v.verdict, "claim": claim.extracted_claim if claim else "",
        "cited_for": narrowed_cited_for(claim) if claim else "",
        "disputed": "yes" if v.consensus_type == "disputed" else "",
        "check_first": "yes" if check_first(v) else "",
        "reasoning": v.reasoning,
        "partial_type": partial_type_of(v) or "", "partial_label": type_label(partial_type_of(v)),
        "partial_severity": severity_of(v) or "", "author_action": action_of(v),
        "unsupported_elements": "; ".join(elements_of(v)),
    }


def build_counts(verifications: list[VerificationResult]) -> dict[str, int]:
    """Build summary counts from verifications."""
    counts: dict[str, int] = {
        "total": len(verifications), "supported": 0,
        "partially_supported": 0, "not_supported": 0,
        "contradicted": 0, "cannot_verify": 0,
    }
    for v in verifications:
        if v.verdict in counts:
            counts[v.verdict] += 1
    return counts


def collect_critical(
    verifications: list[VerificationResult],
    claims_by_id: dict[int, Claim],
) -> list[dict[str, str]]:
    """Collect critical findings (contradicted / not_supported)."""
    return [_finding(v, claims_by_id.get(v.claim_id)) for v in verifications
            if v.verdict in ("not_supported", "contradicted")]


def collect_minor(
    verifications: list[VerificationResult],
    claims_by_id: dict[int, Claim],
) -> list[dict[str, str]]:
    """Collect minor issues (partially_supported); check-first ones lead the list."""
    partial = sorted((v for v in verifications if v.verdict == "partially_supported"),
                     key=lambda v: not check_first(v))
    return [_finding(v, claims_by_id.get(v.claim_id)) for v in partial]


def collect_retracted(refs: list[Reference]) -> list[dict[str, str]]:
    """Collect retracted references."""
    return [
        {
            "ref_id": str(r.id), "title": r.title,
            "status": r.retraction_status,
            "detail": r.retraction_detail,
        }
        for r in refs
        if r.retraction_status not in ("ok", "unknown")
    ]
