"""Verification orchestrator: tiered voting with escalation."""

import logging

from refcheck.llm.cost_tracker import CostTracker
from refcheck.llm.model_registry import ModelConfig, TierConfig
from refcheck.llm.multi_model import call_model, call_models_parallel
from refcheck.llm.vote_helpers import (
    build_tiebreaker,
    fallback_consensus,
    response_to_vote,
    responses_to_votes,
)
from refcheck.llm.voting import determine_consensus
from refcheck.llm.voting_models import ConsensusResult, ModelVote

logger = logging.getLogger(__name__)


class VerificationOrchestrator:
    """Orchestrates multi-tier model voting for claim verification."""

    def __init__(
        self,
        tier_config: TierConfig,
        cost_tracker: CostTracker,
    ) -> None:
        self.tier_config = tier_config
        self.cost_tracker = cost_tracker

    async def verify_one(
        self,
        prompt: str,
        system_prompt: str = "",
        task: str = "verification",
    ) -> ConsensusResult:
        """Run tiered voting for one verification unit.

        Round 1: Tier 0 (3 parallel) -> consensus? Accept.
        Round 2: Tier 1 (2 parallel) -> consensus? Accept.
        Round 3: Tier 2 (1 model) -> final verdict.
        Round 4: Tier 3 (1 model) -> absolute last resort.
        """
        all_votes: list[ModelVote] = []
        path: list[int] = []

        for tier_models, tier_num, suffix, tiebreak in [
            (self.tier_config.tier0, 0, "tier0", False),
            (self.tier_config.tier1, 1, "tier1", False),
            (self.tier_config.tier2[:1], 2, "tier2", True),
        ]:
            result = await self._run_tier(
                tier_models, prompt, system_prompt,
                all_votes, path, tier=tier_num,
                task=f"{task}_{suffix}", is_tiebreaker=tiebreak,
            )
            if result:
                return result

        return await self._run_final(
            self.tier_config.tier3, prompt, system_prompt,
            all_votes, path, task=f"{task}_tier3",
        )

    async def _run_tier(
        self,
        models: list[ModelConfig],
        prompt: str,
        system_prompt: str,
        all_votes: list[ModelVote],
        escalation_path: list[int],
        tier: int,
        task: str,
        is_tiebreaker: bool = False,
    ) -> ConsensusResult | None:
        """Run one tier and check consensus. Returns None to escalate."""
        if not models:
            return None

        escalation_path.append(tier)
        responses = await call_models_parallel(
            models, prompt, system_prompt,
            cost_tracker=self.cost_tracker, task=task,
        )

        new_votes = responses_to_votes(responses, tier)
        all_votes.extend(new_votes)

        if is_tiebreaker and new_votes:
            return build_tiebreaker(all_votes, new_votes[0], escalation_path)

        consensus = determine_consensus(all_votes)
        if consensus.consensus_type != "escalate":
            consensus.final_tier = tier
            consensus.escalation_path = list(escalation_path)
            return consensus

        return None

    async def _run_final(
        self,
        models: list[ModelConfig],
        prompt: str,
        system_prompt: str,
        all_votes: list[ModelVote],
        escalation_path: list[int],
        task: str,
    ) -> ConsensusResult:
        """Tier 3 final resort. Single model, verdict is final."""
        if not models:
            return fallback_consensus(all_votes, escalation_path)

        escalation_path.append(3)
        try:
            response = await call_model(
                models[0], prompt, system_prompt,
                cost_tracker=self.cost_tracker, task=task,
            )
            vote = response_to_vote(response, tier=3)
            if vote:
                all_votes.append(vote)
                return build_tiebreaker(all_votes, vote, escalation_path)
        except Exception as exc:
            logger.warning("Tier 3 failed: %s", exc)

        return fallback_consensus(all_votes, escalation_path)
