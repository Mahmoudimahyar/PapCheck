"""Structured (Pydantic) completion against ONE model: cache, parse, retry."""

import json
import logging
from typing import Generic, TypeVar

from pydantic import BaseModel, Field, ValidationError

from refcheck.llm.cache import get_text, make_key, set_text
from refcheck.llm.completion import complete
from refcheck.llm.cost_tracker import CostTracker
from refcheck.llm.errors import LLMRefusalError, LLMResponseInvalidError
from refcheck.llm.json_extractor import extract_json_from_response
from refcheck.llm.messages import Message, add_correction, build_messages
from refcheck.llm.model_spec import ModelSpec
from refcheck.llm.schema import response_format_for
from refcheck.llm.templates import render_template
from refcheck.llm.types import Role
from refcheck.llm.usage import TokenUsage, compute_cost

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
# The blind cross-check re-runs the verifier's exact prompt: its own cache key keeps it from
# replaying a verifier answer when both resolve to the same model. Other roles keep role-free
# keys, so cache entries written before this rule stay valid.
ROLE_SCOPED_CACHE: frozenset[str] = frozenset({"confirm"})


class LLMCallResult(BaseModel, Generic[T]):
    """Parsed output plus call metadata."""

    content: str
    parsed: T
    usage: TokenUsage = Field(default_factory=TokenUsage)
    latency_ms: int = 0
    model_id: str
    litellm_id: str
    provider: str
    display_name: str = ""
    role: Role | None = None
    reasoning_effort: str | None = None
    cost_usd: float = 0.0
    attempts: int = 1
    from_cache: bool = False


def parse_output(content: str, output_model: type[T]) -> tuple[T, str]:
    """Extract and validate JSON; returns (model, normalized JSON text)."""
    text = extract_json_from_response(content)
    if not text:
        raise ValueError("empty response")
    parsed = output_model.model_validate(json.loads(text))
    return parsed, text


def _result(spec: ModelSpec, role: Role | None, parsed: T, content: str,
            usage: TokenUsage, latency_ms: int, attempts: int, cached: bool) -> LLMCallResult[T]:
    return LLMCallResult(
        content=content, parsed=parsed, usage=usage, latency_ms=latency_ms,
        model_id=spec.id, litellm_id=spec.litellm_id, provider=spec.provider,
        display_name=spec.label, role=role, reasoning_effort=spec.reasoning_effort,
        cost_usd=0.0 if cached else compute_cost(spec, usage), attempts=attempts,
        from_cache=cached,
    )


async def call_spec(
    spec: ModelSpec, user_text: str, system_text: str | None, output_model: type[T],
    role: Role | None, max_retries: int, use_cache: bool, cost_tracker: CostTracker | None,
    task: str, max_output_tokens: int | None, deadline: float | None,
) -> LLMCallResult[T]:
    """Call one model: cache lookup, strict-schema request, parse + retry.

    Invalid JSON gets a correction turn; truncated output (finish_reason
    "length") is retried with a doubled token limit instead.
    """
    if cost_tracker is not None:
        cost_tracker.ensure_budget()
    response_format = response_format_for(spec, output_model)
    parts: dict[str, object] = {
        "model": spec.litellm_id, "effort": spec.reasoning_effort, "user": user_text,
        "system": system_text, "format": response_format, "out": output_model.__name__,
    }
    if role in ROLE_SCOPED_CACHE:
        parts["role"] = role
    key = make_key("chat", parts)
    cached = get_text(key) if use_cache else None
    if cached is not None:
        try:
            parsed, text = parse_output(cached, output_model)
            return _result(spec, role, parsed, text, TokenUsage(), 0, 0, True)
        except (ValueError, ValidationError):
            logger.debug("Ignoring stale cache entry for %s", spec.id)

    messages: list[Message] = build_messages(user_text, system_text, spec.provider)
    usage, latency, max_tokens = TokenUsage(), 0, max_output_tokens or spec.max_output_tokens
    last_error = "no attempt made"
    for attempt in range(1, max_retries + 2):
        outcome = await complete(
            spec, messages, response_format, max_output_tokens=max_tokens,
            deadline=deadline, cost_tracker=cost_tracker, task=task, role=role,
        )
        usage, latency = usage + outcome.usage, latency + outcome.latency_ms
        if outcome.refusal or outcome.finish_reason in ("content_filter", "refusal"):
            raise LLMRefusalError(f"{spec.id} refused: {outcome.refusal or 'content filter'}",
                                  spec.id)
        try:
            parsed, text = parse_output(outcome.content, output_model)
        except (ValueError, ValidationError) as exc:
            last_error = f"{type(exc).__name__}: {str(exc)[:300]}"
            logger.warning("%s invalid output (%d/%d, finish=%s): %s", spec.id, attempt,
                           max_retries + 1, outcome.finish_reason, last_error[:200])
            if outcome.finish_reason == "length":
                last_error = f"output truncated at {max_tokens} tokens"
                max_tokens = min(max_tokens * 2, 4 * spec.max_output_tokens)
            else:
                correction = render_template("llm_json_retry", {"error": last_error})
                messages = add_correction(messages, outcome.content, correction)
            continue
        if use_cache:
            set_text(key, text)
        return _result(spec, role, parsed, text, usage, latency, attempt, False)
    raise LLMResponseInvalidError(
        f"{spec.id}: invalid output after {max_retries + 1} attempts: {last_error}",
        model_id=spec.id,
    )
