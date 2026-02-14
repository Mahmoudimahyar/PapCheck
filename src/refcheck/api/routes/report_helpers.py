"""Helper functions for report preview and diff endpoints."""

from refcheck.models.claim import Claim
from refcheck.models.reference import Reference
from refcheck.models.verification import VerificationResult


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
    critical: list[dict[str, str]] = []
    for v in verifications:
        if v.verdict in ("not_supported", "contradicted"):
            claim = claims_by_id.get(v.claim_id)
            critical.append({
                "claim_id": str(v.claim_id), "verdict": v.verdict,
                "claim": claim.extracted_claim if claim else "",
                "reasoning": v.reasoning,
            })
    return critical


def collect_minor(
    verifications: list[VerificationResult],
    claims_by_id: dict[int, Claim],
) -> list[dict[str, str]]:
    """Collect minor issues (partially_supported)."""
    return [
        {
            "claim_id": str(v.claim_id), "verdict": v.verdict,
            "claim": (
                claims_by_id[v.claim_id].extracted_claim
                if v.claim_id in claims_by_id else ""
            ),
        }
        for v in verifications
        if v.verdict == "partially_supported"
    ]


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
