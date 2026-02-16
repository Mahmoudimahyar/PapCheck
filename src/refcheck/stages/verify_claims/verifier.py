"""LLM-powered claim verification with multi-model voting (V4)."""

import asyncio
import logging
import os

from refcheck.llm.concurrency import get_llm_semaphore
from refcheck.llm.cost_tracker import CostTracker
from refcheck.llm.env_setup import setup_llm_env_vars
from refcheck.llm.model_availability import build_tier_config, get_available_models
from refcheck.llm.orchestrator import VerificationOrchestrator
from refcheck.llm.templates import render_template
from refcheck.llm.voting_models import ConsensusResult
from refcheck.models.claim import Claim
from refcheck.models.reference import Reference
from refcheck.models.verification import VerificationResult, VoteRecord
from refcheck.stages.verify_claims.evidence_builder import build_evidence_sections
from refcheck.stages.verify_claims.verifier_helpers import (
    SourceCoverage,
    apply_claim_type_behavior,
    cannot_verify,
    get_source_text,
)

logger = logging.getLogger(__name__)


async def verify_claims(
    claims: list[Claim],
    references: list[Reference],
    cost_tracker: CostTracker | None = None,
) -> list[VerificationResult]:
    """Verify all claims using multi-model voting (V4).

    Uses tiered voting: cheap models do bulk work, expensive models
    only break ties. Cost drops ~98%.
    """
    providers = setup_llm_env_vars()
    available = get_available_models(providers)
    tier_config = build_tier_config(available)
    tracker = cost_tracker or CostTracker()
    orch = VerificationOrchestrator(tier_config, tracker)

    ref_by_id: dict[int, Reference] = {r.id: r for r in references}
    sem = get_llm_semaphore()
    concurrency = int(os.environ.get("REFCHECK_LLM_CONCURRENCY", "5"))
    sem = asyncio.Semaphore(concurrency)

    pairs: list[tuple[Claim, Reference]] = []
    for claim in claims:
        for ref_id in claim.reference_ids:
            ref = ref_by_id.get(ref_id)
            if not ref:
                logger.warning("Ref %d not found for claim %d", ref_id, claim.id)
                continue
            pairs.append((claim, ref))

    logger.info("Verifying %d claim-reference pairs (multi-model)", len(pairs))

    async def _guarded(c: Claim, r: Reference) -> VerificationResult:
        async with sem:
            return await _verify_single(c, r, orch)

    results = list(await asyncio.gather(*[_guarded(c, r) for c, r in pairs]))
    _log_tier_stats(results)
    return results


async def _verify_single(
    claim: Claim,
    ref: Reference,
    orch: VerificationOrchestrator,
) -> VerificationResult:
    """Verify a single claim-reference pair using multi-model voting."""
    source_text, coverage, sections, headings = get_source_text(claim, ref)

    if coverage == "no_source":
        return cannot_verify(claim, ref, "No source text available")

    prompt = _build_prompt(claim, ref, source_text)
    consensus = await orch.verify_one(prompt, task="verification")
    result = _consensus_to_result(consensus, claim, ref, coverage)
    result = apply_claim_type_behavior(result, claim)

    ev_sections = build_evidence_sections(
        source_sections=sections, source_headings=headings,
        evidence_quotes=result.evidence_quotes,
        source_text=source_text, claim_text=claim.extracted_claim,
    )
    return result.model_copy(update={"evidence_sections": ev_sections})


def _build_prompt(claim: Claim, ref: Reference, source_text: str) -> str:
    """Render the verification prompt template."""
    authors_str = ", ".join(ref.authors[:3]) if ref.authors else "Unknown"
    variables: dict[str, str] = {
        "claim": claim.extracted_claim,
        "claim_type": claim.claim_type,
        "source_sections": source_text,
        "reference_title": ref.title or "Unknown",
        "reference_authors": authors_str,
    }
    if claim.atomic_claims:
        variables["atoms"] = "|||".join(claim.atomic_claims)
    return render_template("grounded_verification", variables)


def _consensus_to_result(
    consensus: ConsensusResult,
    claim: Claim,
    ref: Reference,
    coverage: SourceCoverage,
) -> VerificationResult:
    """Convert a ConsensusResult to a VerificationResult."""
    verdict = consensus.verdict
    if verdict == "escalate":
        verdict = "cannot_verify"
    valid_verdicts = {
        "supported", "partially_supported", "not_supported",
        "contradicted", "cannot_verify",
    }
    if verdict not in valid_verdicts:
        verdict = "cannot_verify"

    votes = [
        VoteRecord(
            model_name=v.model_name, abbreviation=v.abbreviation,
            tier=v.tier, verdict=v.verdict, confidence=v.confidence,
        )
        for v in consensus.votes
    ]
    return VerificationResult(
        claim_id=claim.id, reference_id=ref.id,
        verdict=verdict,  # type: ignore[arg-type]
        confidence=min(1.0, max(0.0, consensus.confidence)),
        evidence_quotes=consensus.merged_evidence,
        reasoning=consensus.merged_reasoning,
        tier=consensus.final_tier,
        source_coverage=coverage,
        needs_user_review=verdict == "contradicted",
        votes=votes,
        consensus_type=consensus.consensus_type,
        final_tier=consensus.final_tier,
        escalation_path=consensus.escalation_path,
        total_models_consulted=len(consensus.votes),
        agreement_ratio=consensus.agreement_ratio,
    )


def _log_tier_stats(results: list[VerificationResult]) -> None:
    """Log counts of results at each consensus tier."""
    tiers: dict[int, int] = {}
    for r in results:
        tiers[r.final_tier] = tiers.get(r.final_tier, 0) + 1
    review = sum(1 for r in results if r.needs_user_review)
    logger.info(
        "Verified %d: tiers=%s review=%d",
        len(results), tiers, review,
    )
