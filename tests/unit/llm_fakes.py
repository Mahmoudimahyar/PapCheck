"""Shared fakes for refcheck.llm unit tests (no network, fake keys only)."""

import os
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import litellm
import pytest

from refcheck.llm import cache, degradation, keys, limits, retry, roles

FAKE_OPENAI = "sk-test-openai-0000000000"
FAKE_ANTH_PRIMARY = "sk-ant-test-primary-000000"
FAKE_ANTH_BACKUP = "sk-ant-test-backup-0000000"

_CLEARED_PREFIXES = ("REFCHECK_",)
_PROVIDER_VARS = (
    "OPENAI_API_KEY", "OPENAI_API_KEY_BACKUP", "ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY_BACKUP",
    "GEMINI_API_KEY", "GOOGLE_API_KEY", "XAI_API_KEY", "GROK_API_KEY", "NVIDIA_API_KEY",
    "NVIDIA_NIM_API_KEY",
)


def _reset() -> None:
    keys.reset_keys()
    roles.reset_availability()
    limits.reset_limits()
    cache.close_caches()
    degradation.clear()
    from refcheck.llm import health

    health.clear_preflight_cache()


def isolated_llm_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Fake keys, temp cache/state dirs, no backoff sleeps, clean registries."""
    for name in list(os.environ):
        if name.startswith(_CLEARED_PREFIXES) or name in _PROVIDER_VARS:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_OPENAI)
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_ANTH_PRIMARY)
    monkeypatch.setenv("ANTHROPIC_API_KEY_BACKUP", FAKE_ANTH_BACKUP)
    monkeypatch.setenv("REFCHECK_KEY_STATE_FILE", str(tmp_path / "key_state.json"))
    monkeypatch.setenv("REFCHECK_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("REFCHECK_LLM_MAX_ATTEMPTS", "3")
    monkeypatch.setattr(retry, "backoff_delay", lambda attempt: 0.0)
    _reset()
    yield
    _reset()


def chat_response(
    content: str,
    prompt_tokens: int = 100,
    completion_tokens: int = 20,
    cached: int = 0,
    cache_write: int = 0,
    finish: str = "stop",
    refusal: str | None = None,
) -> SimpleNamespace:
    """Shape-compatible stand-in for a litellm ModelResponse."""
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        prompt_tokens_details=SimpleNamespace(cached_tokens=cached),
        completion_tokens_details=SimpleNamespace(reasoning_tokens=0),
        cache_read_input_tokens=cached, cache_creation_input_tokens=cache_write,
    )
    message = SimpleNamespace(content=content, refusal=refusal)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish)], usage=usage,
    )


def predicate(name: str | None, probability: float) -> SimpleNamespace:
    return SimpleNamespace(type="predicate", name=name, probability=probability)


def refusal(name: str | None) -> SimpleNamespace:
    return SimpleNamespace(type="refusal", name=name)


def choice(name: str, picked: object, probs: dict[object, float]) -> SimpleNamespace:
    return SimpleNamespace(
        type="choice", name=name, choice=picked, confidence=max(probs.values()),
        probabilities=tuple(SimpleNamespace(value=v, probability=p) for v, p in probs.items()),
    )


def decision_response(answers: list[SimpleNamespace], input_tokens: int = 500,
                      cached: int = 0) -> SimpleNamespace:
    usage = SimpleNamespace(
        input_tokens=input_tokens, output_tokens=0, total_tokens=input_tokens,
        input_tokens_details=SimpleNamespace(cached_tokens=cached, cache_write_tokens=0),
    )
    return SimpleNamespace(model="gpt-6-luna", answers=tuple(answers), usage=usage)


def embedding_response(vectors: list[list[float]], tokens: int = 10) -> SimpleNamespace:
    data = [{"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vectors)]
    return SimpleNamespace(data=list(reversed(data)), usage=SimpleNamespace(prompt_tokens=tokens))


def billing_error() -> Exception:
    return litellm.exceptions.BadRequestError(
        "AnthropicException - Your credit balance is too low to access the Anthropic API.",
        "claude-sonnet-5-5", "anthropic",
    )


def rate_limit_error() -> Exception:
    return litellm.exceptions.RateLimitError("Rate limit reached", "openai", "gpt-6-luna")


def not_found_error() -> Exception:
    return litellm.exceptions.NotFoundError("model_not_found", "gpt-6-luna", "openai")


def auth_error() -> Exception:
    return litellm.exceptions.AuthenticationError(
        f"Incorrect API key provided: {FAKE_OPENAI}", "openai", "gpt-6-luna",
    )
