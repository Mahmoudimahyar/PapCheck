"""call_provider retries/backoff/key rotation and provider semaphores."""

import asyncio
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import litellm
import pytest

from refcheck.llm import keys, limits
from refcheck.llm.errors import LLMCallError
from refcheck.llm.retry import backoff_delay, call_provider, deadline_from
from tests.unit.llm_fakes import (
    FAKE_ANTH_BACKUP,
    FAKE_ANTH_PRIMARY,
    billing_error,
    isolated_llm_env,
    not_found_error,
    rate_limit_error,
)


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    yield from isolated_llm_env(monkeypatch, tmp_path)


class _Script:
    """Sync callable that raises/returns according to a script."""

    def __init__(self, *steps: object) -> None:
        self.steps = list(steps)
        self.keys_seen: list[str] = []
        self.timeouts: list[float] = []

    def __call__(self, api_key: str, timeout: float) -> object:
        self.keys_seen.append(api_key)
        self.timeouts.append(timeout)
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


async def _call(fn: _Script, provider: str = "openai", **kw: object) -> object:
    return await call_provider(fn, provider=provider, label="m", timeout=30.0, **kw)  # type: ignore[arg-type]


class TestRetries:
    async def test_success_first_try(self) -> None:
        fn = _Script("ok")
        assert await _call(fn) == "ok"
        assert fn.timeouts == [30.0]

    async def test_rate_limit_retried_then_succeeds(self) -> None:
        fn = _Script(rate_limit_error(), rate_limit_error(), "ok")
        assert await _call(fn) == "ok"
        assert len(fn.keys_seen) == 3

    async def test_rate_limit_gives_up_after_max_attempts(self) -> None:
        fn = _Script(rate_limit_error(), rate_limit_error(), rate_limit_error(), "never")
        with pytest.raises(LLMCallError) as info:
            await _call(fn)
        assert info.value.kind == "rate_limit"
        assert len(fn.keys_seen) == 3  # REFCHECK_LLM_MAX_ATTEMPTS=3 in the fixture

    async def test_not_found_is_not_retried(self) -> None:
        fn = _Script(not_found_error(), "never")
        with pytest.raises(LLMCallError) as info:
            await _call(fn)
        assert info.value.kind == "not_found" and info.value.is_hard
        assert len(fn.keys_seen) == 1


class TestKeyRotation:
    async def test_billing_error_rotates_to_backup_key(self) -> None:
        fn = _Script(billing_error(), "ok")
        assert await _call(fn, provider="anthropic") == "ok"
        assert fn.keys_seen == [FAKE_ANTH_PRIMARY, FAKE_ANTH_BACKUP]
        assert keys.current_slot("anthropic") == "ANTHROPIC_API_KEY_BACKUP"

    async def test_all_keys_exhausted_raises_billing(self) -> None:
        fn = _Script(billing_error(), billing_error(), "never")
        with pytest.raises(LLMCallError) as info:
            await _call(fn, provider="anthropic")
        assert info.value.kind == "billing"
        assert not keys.has_key("anthropic")

    async def test_invalid_key_401_rotates(self) -> None:
        bad_key = litellm.exceptions.AuthenticationError("invalid x-api-key", "anthropic",
                                                         "claude-sonnet-5-5")
        fn = _Script(bad_key, "ok")
        assert await _call(fn, provider="anthropic") == "ok"
        assert fn.keys_seen == [FAKE_ANTH_PRIMARY, FAKE_ANTH_BACKUP]

    async def test_model_level_403_does_not_condemn_the_key(self) -> None:
        denied = litellm.exceptions.PermissionDeniedError(
            "not allowed to use this model", "anthropic", "claude-opus-5-5",
            response=_response(403))
        fn = _Script(denied, "never")
        with pytest.raises(LLMCallError) as info:
            await _call(fn, provider="anthropic")
        assert info.value.kind == "auth" and info.value.is_hard  # benches the model only
        assert fn.keys_seen == [FAKE_ANTH_PRIMARY]
        assert keys.current_slot("anthropic") == "ANTHROPIC_API_KEY"

    async def test_known_exhausted_key_is_skipped_up_front(self) -> None:
        keys.rotate("anthropic", FAKE_ANTH_PRIMARY, "billing")
        keys.reset_keys()
        fn = _Script("ok")
        await _call(fn, provider="anthropic")
        assert fn.keys_seen == [FAKE_ANTH_BACKUP]

    async def test_no_key_raises_unavailable(self) -> None:
        fn = _Script("never")
        with pytest.raises(LLMCallError) as info:
            await _call(fn, provider="gemini")
        assert info.value.kind == "unavailable"
        assert fn.keys_seen == []


class TestDeadline:
    async def test_attempt_timeout_capped_by_deadline(self) -> None:
        fn = _Script("ok")
        await _call(fn, deadline=deadline_from(5.0))
        assert 3.0 < fn.timeouts[0] <= 5.0

    async def test_exhausted_budget_raises_timeout_without_calling(self) -> None:
        fn = _Script("never")
        with pytest.raises(LLMCallError) as info:
            await _call(fn, deadline=time.monotonic() + 0.1)
        assert info.value.kind == "timeout"
        assert fn.keys_seen == []

    def test_backoff_is_bounded(self) -> None:
        for attempt in range(1, 10):
            assert 0 <= backoff_delay(attempt) <= 20.0


class TestLimits:
    def test_defaults_and_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert limits.provider_limit("openai") == 32
        assert limits.provider_limit("anthropic") == 16
        assert limits.provider_limit("gemini") == 8
        monkeypatch.setenv("REFCHECK_OPENAI_CONCURRENCY", "3")
        assert limits.provider_limit("openai") == 3
        monkeypatch.setenv("REFCHECK_OPENAI_CONCURRENCY", "lots")
        assert limits.provider_limit("openai") == 32

    async def test_semaphore_bounds_in_flight_calls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REFCHECK_OPENAI_CONCURRENCY", "2")
        limits.reset_limits()
        lock = threading.Lock()
        state = {"now": 0, "peak": 0}

        def slow(api_key: str, timeout: float) -> str:
            with lock:
                state["now"] += 1
                state["peak"] = max(state["peak"], state["now"])
            time.sleep(0.05)
            with lock:
                state["now"] -= 1
            return "ok"

        await asyncio.gather(*[
            call_provider(slow, provider="openai", label="m", timeout=5.0) for _ in range(6)
        ])
        assert state["peak"] == 2

    def test_semaphores_are_per_event_loop(self) -> None:
        async def get() -> asyncio.Semaphore:
            return limits.provider_semaphore("openai")

        assert asyncio.run(get()) is not asyncio.run(get())


def _response(status: int) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("POST", "https://api.example.test"))
