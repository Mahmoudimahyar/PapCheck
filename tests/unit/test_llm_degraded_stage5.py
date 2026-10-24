"""V5.8: stage 5's preflight with the OpenAI account out of credits (fakes only).

Before V5.8 this raised "no working model for role(s) confirm"; now confirm runs
on a same-family Anthropic fallback, the screen is skipped, and the run's
tracker records both with the cause (billing) and the fix.
"""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from refcheck.llm import keys
from refcheck.llm.client import call_llm_raw
from refcheck.llm.cost_tracker import CostTracker
from refcheck.llm.errors import LLMCallError, LLMRefusalError
from refcheck.llm.model_spec import ModelSpec
from refcheck.llm.roles import mark_unavailable, resolve_role, role_status
from refcheck.stages.verify_claims.calibration import ScreenThresholds
from refcheck.stages.verify_claims.verifier import VerificationRun, _preflight
from tests.unit.llm_fakes import chat_response, isolated_llm_env

_OPENAI_PREFIXES = ("gpt-", "text-embedding")


class Out(BaseModel):
    summary: str
    confidence: float


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    yield from isolated_llm_env(monkeypatch, tmp_path)


async def _no_credits(spec: ModelSpec, role: str, tracker: object = None,
                      timeout: float = 45.0) -> None:
    if spec.id.startswith(_OPENAI_PREFIXES):
        raise LLMCallError("Error code: 429 - insufficient_quota", "billing", spec.id)


async def test_stage5_preflight_degrades_instead_of_failing() -> None:
    tracker = CostTracker()
    run = VerificationRun(tracker=tracker, thresholds=ScreenThresholds(), budget=60.0)
    with patch("refcheck.llm.health.probe_model", AsyncMock(side_effect=_no_credits)):
        await _preflight(run)  # must not raise
    assert run.thresholds.enabled is False  # screen skipped
    assert set(tracker.degradations) == {"confirm", "screen"}
    confirm = tracker.degradations["confirm"]
    assert confirm.fallback_model == "claude-sonnet-5-5" and confirm.cause == "billing"
    assert confirm.persistent and confirm.action is not None
    assert "Add credits to the OpenAI account" in tracker.summary().degraded["screen"]


async def test_a_refusal_is_not_an_outage() -> None:
    """With OpenAI working, a refused confirm answer must not switch to the fallback."""
    refused = chat_response("", refusal="I can't help with that.")
    mock = MagicMock(return_value=refused)
    with patch("refcheck.llm.completion._sync_completion", mock), \
            pytest.raises(LLMRefusalError):
        await call_llm_raw("test_prompt", {"topic": "x"}, Out, role="confirm",
                           use_cache=False, max_retries=0)
    called = {c.args[0]["model"] for c in mock.call_args_list}
    assert called == {"openai/gpt-6-luna"}


def test_cascade_confirm_is_same_family_when_degraded() -> None:
    from refcheck.stages.verify_claims.escalation import confirm_model, families_match
    from refcheck.stages.verify_claims.layers import LayerResult

    keys.rotate("openai", reason="billing")
    l2 = LayerResult(layer="verifier", role="verifier", model_id="claude-haiku-5-5")
    assert confirm_model(l2) is None  # no other family left: role resolution decides
    spec = resolve_role("confirm")
    assert spec is not None and spec.id == "claude-sonnet-5-5"
    confirm = LayerResult(layer="confirm", role="confirm", model_id=spec.id)
    assert families_match(l2, confirm)  # -> "same family only", queued for review


def test_cross_family_fallback_is_not_called_same_family(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFCHECK_VERIFIER_MODEL", "gpt-6-luna")
    monkeypatch.setenv("REFCHECK_CONFIRM_MODEL", "gpt-6.1-sol")
    mark_unavailable("gpt-6.1-sol", "not_found: gone")
    status = role_status()["confirm"]
    assert status.model_id == "claude-sonnet-5-5" and status.degraded
    assert "same model family" not in (status.effect or "")
