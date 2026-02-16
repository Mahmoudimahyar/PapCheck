"""Tests for verification orchestrator (all LLM calls mocked)."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from refcheck.llm.cost_tracker import CostTracker
from refcheck.llm.model_registry import ModelConfig, TierConfig
from refcheck.llm.orchestrator import VerificationOrchestrator


def _model(alias: str, tier: int = 0) -> ModelConfig:
    return ModelConfig(
        alias=alias, name=f"Test {alias}", abbreviation=alias[:2].upper(),
        litellm_id=f"test/{alias}", tier=tier,
        input_cost_per_m=0.0, output_cost_per_m=0.0,
        max_context=128_000, provider="test", env_key="TEST_KEY",
    )


def _tier_config() -> TierConfig:
    return TierConfig(
        tier0=[_model("m0a", 0), _model("m0b", 0), _model("m0c", 0)],
        tier1=[_model("m1a", 1), _model("m1b", 1)],
        tier2=[_model("m2", 2)],
        tier3=[_model("m3", 3)],
    )


def _mock_resp(
    verdict: str = "supported",
    confidence: float = 0.85,
    model_alias: str = "test",
) -> SimpleNamespace:
    """Create a mock litellm response."""
    import json
    content = json.dumps({
        "verdict": verdict,
        "confidence": confidence,
        "reasoning": f"Model says {verdict}",
        "evidence_quotes": [f"Evidence for {verdict}"],
    })
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    usage = SimpleNamespace(prompt_tokens=100, completion_tokens=50)
    return SimpleNamespace(choices=[choice], usage=usage)


class TestTier0Resolves:
    """VO-01: Tier 0 resolves -> no escalation."""

    @pytest.mark.asyncio
    async def test_tier0_unanimous_no_escalation(self) -> None:
        tc = _tier_config()
        tracker = CostTracker()
        orch = VerificationOrchestrator(tc, tracker)

        with patch(
            "refcheck.llm.multi_model._sync_completion",
            return_value=_mock_resp("supported", 0.90),
        ):
            result = await orch.verify_one("test prompt")

        assert result.verdict == "supported"
        assert result.consensus_type == "unanimous"
        assert result.final_tier == 0
        assert result.escalation_path == [0]


class TestTier0FailsTier1Resolves:
    """VO-02: Tier 0 fails -> Tier 1 resolves."""

    @pytest.mark.asyncio
    async def test_escalation_to_tier1(self) -> None:
        tc = _tier_config()
        tracker = CostTracker()
        orch = VerificationOrchestrator(tc, tracker)
        call_count = 0

        def mock_completion(
            model_id: str,
            messages: list[dict[str, str]],
            timeout: int,
            max_tokens: int,
        ) -> SimpleNamespace:
            nonlocal call_count
            call_count += 1
            import json
            # Tier 0: all different -> escalate
            if call_count <= 3:
                verdicts = ["supported", "not_supported", "partially_supported"]
                v = verdicts[call_count - 1]
                content = json.dumps({
                    "verdict": v, "confidence": 0.70,
                    "reasoning": f"{v}", "evidence_quotes": ["q"],
                })
            else:
                # Tier 1: both agree
                content = json.dumps({
                    "verdict": "supported", "confidence": 0.85,
                    "reasoning": "Tier 1 agrees", "evidence_quotes": ["q"],
                })
            msg = SimpleNamespace(content=content)
            ch = SimpleNamespace(message=msg)
            us = SimpleNamespace(prompt_tokens=100, completion_tokens=50)
            return SimpleNamespace(choices=[ch], usage=us)

        with patch(
            "refcheck.llm.multi_model._sync_completion",
            side_effect=mock_completion,
        ):
            result = await orch.verify_one("test prompt")

        assert result.verdict == "supported"
        assert 0 in result.escalation_path
        assert 1 in result.escalation_path


class TestAllTiersTiebreaker:
    """VO-03: All tiers -> Tier 2 tiebreaker."""

    @pytest.mark.asyncio
    async def test_tier2_tiebreaker(self) -> None:
        tc = _tier_config()
        tracker = CostTracker()
        orch = VerificationOrchestrator(tc, tracker)
        call_count = 0

        def mock_completion(
            model_id: str,
            messages: list[dict[str, str]],
            timeout: int,
            max_tokens: int,
        ) -> SimpleNamespace:
            nonlocal call_count
            call_count += 1
            import json
            # T0: split, T1: split, T2: tiebreaker
            if call_count <= 3:
                vs = ["supported", "not_supported", "partially_supported"]
                v = vs[call_count - 1]
            elif call_count <= 5:
                vs2 = ["supported", "not_supported"]
                v = vs2[call_count - 4]
            else:
                v = "partially_supported"
            content = json.dumps({
                "verdict": v, "confidence": 0.80,
                "reasoning": f"Final: {v}", "evidence_quotes": ["q"],
            })
            msg = SimpleNamespace(content=content)
            ch = SimpleNamespace(message=msg)
            us = SimpleNamespace(prompt_tokens=100, completion_tokens=50)
            return SimpleNamespace(choices=[ch], usage=us)

        with patch(
            "refcheck.llm.multi_model._sync_completion",
            side_effect=mock_completion,
        ):
            result = await orch.verify_one("test prompt")

        assert result.consensus_type == "tiebreaker"
        assert 2 in result.escalation_path
