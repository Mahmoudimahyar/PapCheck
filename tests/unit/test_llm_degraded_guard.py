"""V5.8 degraded mode: the spending cap holds under concurrency, and transient soft-role
failures are not reported as a run-wide outage (fakes only, no network)."""

import asyncio
import time
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from refcheck.llm import degradation, keys
from refcheck.llm.client import call_llm_raw
from refcheck.llm.cost_tracker import CostLimitExceededError, CostTracker
from refcheck.llm.degraded_guard import TRANSIENT_MIN, guard_degraded, note_soft_failure
from refcheck.llm.model_registry import REGISTRY
from refcheck.llm.usage import TokenUsage, compute_cost
from tests.unit.llm_fakes import chat_response, isolated_llm_env

SONNET = REGISTRY["claude-sonnet-5-5"]


class Out(BaseModel):
    summary: str
    confidence: float


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    yield from isolated_llm_env(monkeypatch, tmp_path)


def test_reservations_stop_calls_once_the_cap_is_held(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFCHECK_DEGRADED_MAX_USD", "0.05")
    keys.rotate("openai", reason="billing")
    tracker = CostTracker()
    first = guard_degraded("confirm", SONNET, tracker, None)
    second = guard_degraded("confirm", SONNET, tracker, None)  # 0.03 held < 0.05
    assert first == second == pytest.approx(0.03)
    with pytest.raises(CostLimitExceededError, match="reserved"):
        guard_degraded("confirm", SONNET, tracker, None)  # 0.06 held: no third call
    tracker.release("confirm", first)
    tracker.release("confirm", second)
    assert guard_degraded("confirm", SONNET, tracker, None) > 0
    assert guard_degraded("confirm", REGISTRY["gpt-6-luna"], tracker, None) == 0.0  # normal


async def test_concurrent_degraded_calls_stay_within_the_cap(
        monkeypatch: pytest.MonkeyPatch) -> None:
    cap = 0.1
    monkeypatch.setenv("REFCHECK_DEGRADED_MAX_USD", str(cap))
    keys.rotate("openai", reason="billing")
    tracker = CostTracker()
    tokens = 6_000
    per_call = compute_cost(SONNET, TokenUsage(input_tokens=tokens, output_tokens=20))

    def slow(*_: object, **__: object) -> SimpleNamespace:
        time.sleep(0.05)  # every call is in flight before any is recorded
        return chat_response('{"summary": "s", "confidence": 0.5}', prompt_tokens=tokens)

    async def one(i: int) -> bool:
        try:
            await call_llm_raw("test_prompt", {"topic": f"x{i}"}, Out, role="confirm",
                               cost_tracker=tracker, use_cache=False)
            return True
        except CostLimitExceededError:
            return False

    with patch("refcheck.llm.completion._sync_completion", MagicMock(side_effect=slow)):
        done = await asyncio.gather(*(one(i) for i in range(12)))
    spent = tracker.spent("confirm", {SONNET.id})
    assert sum(done) < 12 and spent <= cap + per_call + 1e-9


def test_a_few_transient_soft_failures_are_not_an_outage() -> None:
    tracker = CostTracker()
    for _ in range(TRANSIENT_MIN - 1):
        note_soft_failure("embedding", "text-embedding-3-small", "timeout", "timed out", tracker)
    assert "embedding" not in tracker.degradations
    note_soft_failure("embedding", "text-embedding-3-small", "timeout", "timed out", tracker)
    item = tracker.degradations["embedding"]
    assert item.failures == TRANSIENT_MIN and not item.persistent
    assert f"for {TRANSIENT_MIN} failed calls" in degradation.describe(item)


def test_a_persistent_cause_replaces_a_transient_one() -> None:
    tracker = CostTracker()
    for _ in range(TRANSIENT_MIN):
        note_soft_failure("embedding", "text-embedding-3-small", "timeout", "timed out", tracker)
    note_soft_failure("embedding", "text-embedding-3-small", "billing", "insufficient_quota",
                      tracker)
    item = tracker.degradations["embedding"]
    assert item.cause == "billing" and item.persistent
    assert "Add credits" in tracker.summary().degraded["embedding"]
    note_soft_failure("embedding", "text-embedding-3-small", "timeout", "timed out", tracker)
    assert tracker.degradations["embedding"].cause == "billing"  # never the other way round
