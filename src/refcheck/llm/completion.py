"""One chat completion against one ModelSpec (no parsing, no fallback).

Never sends temperature (Claude 5.5 rejects it; OpenAI reasoning models
reject it when effort != none); reasoning_effort comes from the spec.
"""

import logging
import time

import litellm
from pydantic import BaseModel

from refcheck.llm.cost_tracker import CostTracker
from refcheck.llm.errors import LLMCallError
from refcheck.llm.messages import Message
from refcheck.llm.model_spec import ModelSpec
from refcheck.llm.retry import call_provider
from refcheck.llm.usage import TokenUsage, usage_from_response

logger = logging.getLogger(__name__)

litellm.suppress_debug_info = True

DEFAULT_TIMEOUT_S = 30.0


class CompletionOutcome(BaseModel):
    """Raw result of one successful completion request."""

    content: str
    usage: TokenUsage
    latency_ms: int
    finish_reason: str | None = None
    refusal: str | None = None


def _sync_completion(kwargs: dict[str, object]) -> object:
    """Blocking litellm call (patched in tests)."""
    return litellm.completion(**kwargs)


def completion_kwargs(
    spec: ModelSpec,
    messages: list[Message],
    response_format: dict[str, object] | None,
    max_output_tokens: int | None,
) -> dict[str, object]:
    """litellm.completion kwargs without api_key/timeout."""
    kwargs: dict[str, object] = {
        "model": spec.litellm_id,
        "messages": messages,
        "max_tokens": max_output_tokens or spec.max_output_tokens,
    }
    if spec.reasoning_effort is not None:
        kwargs["reasoning_effort"] = spec.reasoning_effort
    if response_format is not None:
        kwargs["response_format"] = response_format
    return kwargs


def _outcome(response: object, latency_ms: int) -> CompletionOutcome:
    choices = getattr(response, "choices", None) or []
    first = choices[0] if choices else None
    message = getattr(first, "message", None)
    content = getattr(message, "content", None)
    refusal = getattr(message, "refusal", None)
    finish = getattr(first, "finish_reason", None)
    return CompletionOutcome(
        content=content if isinstance(content, str) else "",
        usage=usage_from_response(response),
        latency_ms=latency_ms,
        finish_reason=finish if isinstance(finish, str) else None,
        refusal=refusal if isinstance(refusal, str) and refusal else None,
    )


async def complete(
    spec: ModelSpec,
    messages: list[Message],
    response_format: dict[str, object] | None,
    *,
    max_output_tokens: int | None = None,
    deadline: float | None = None,
    cost_tracker: CostTracker | None = None,
    task: str = "llm",
    role: str | None = None,
) -> CompletionOutcome:
    """Run one completion with retries; record cost (failures too)."""
    kwargs = completion_kwargs(spec, messages, response_format, max_output_tokens)

    def run(api_key: str, timeout: float) -> object:
        return _sync_completion({**kwargs, "api_key": api_key, "timeout": timeout})

    start = time.perf_counter()
    try:
        response = await call_provider(
            run, provider=spec.provider, label=spec.id,
            timeout=spec.timeout_s or DEFAULT_TIMEOUT_S, deadline=deadline,
        )
    except LLMCallError:
        if cost_tracker is not None:
            cost_tracker.record_usage(
                spec, TokenUsage(), task, role,
                int((time.perf_counter() - start) * 1000), success=False,
            )
        raise
    outcome = _outcome(response, int((time.perf_counter() - start) * 1000))
    if cost_tracker is not None:
        cost_tracker.record_usage(spec, outcome.usage, task, role, outcome.latency_ms)
    logger.debug("%s ok in %dms (in=%d cached=%d out=%d)", spec.id, outcome.latency_ms,
                 outcome.usage.input_tokens, outcome.usage.cached_input_tokens,
                 outcome.usage.output_tokens)
    return outcome
