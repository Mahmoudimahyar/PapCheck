"""OpenAI Decisions API (``litellm.decisions``) with retries and cost tracking.

litellm has no retry logic on this path, so calls go through
``retry.call_provider``. Refusals come back as answer type "refusal" (HTTP
200) and are returned as ``refused=True`` answers, never as errors. More
than 128 questions are split into several requests over the same input.
Cost = input tokens x $0.10/M (no output or cache charges).
"""

import asyncio
import logging
import time
from collections.abc import Sequence

import litellm

from refcheck.llm.cost_tracker import CostTracker
from refcheck.llm.decision_models import (
    DecisionAnswer,
    DecisionError,
    DecisionQuestion,
    DecisionResult,
)
from refcheck.llm.degraded_guard import note_soft_failure
from refcheck.llm.errors import LLMCallError, short_error
from refcheck.llm.model_lookup import spec_for
from refcheck.llm.model_spec import ModelSpec
from refcheck.llm.retry import call_provider, deadline_from
from refcheck.llm.roles import mark_unavailable, resolve_role
from refcheck.llm.types import Role
from refcheck.llm.usage import TokenUsage, compute_cost

logger = logging.getLogger(__name__)

__all__ = [
    "DecisionAnswer", "DecisionError", "DecisionQuestion", "DecisionResult", "decide",
]

MAX_QUESTIONS_PER_REQUEST = 128
_DEFAULT_TIMEOUT_S = 20.0


def _sync_decisions(kwargs: dict[str, object]) -> object:
    """Blocking litellm call (patched in tests)."""
    return litellm.decisions(**kwargs)


def _chunks(questions: Sequence[DecisionQuestion]) -> list[list[DecisionQuestion]]:
    size = MAX_QUESTIONS_PER_REQUEST
    return [list(questions[i:i + size]) for i in range(0, len(questions), size)]


def _choice_key(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _answer(raw: object, name: str) -> DecisionAnswer:
    kind = getattr(raw, "type", None)
    if kind == "predicate":
        prob = getattr(raw, "probability", None)
        if isinstance(prob, (int, float)):
            return DecisionAnswer(name=name, type="predicate", probability=float(prob))
    elif kind == "choice":
        probs = {_choice_key(getattr(p, "value", "")): float(getattr(p, "probability", 0.0))
                 for p in getattr(raw, "probabilities", ()) or ()}
        choice = _choice_key(getattr(raw, "choice", ""))
        return DecisionAnswer(name=name, type="choice", choice=choice,
                              probability=probs.get(choice), probabilities=probs)
    elif kind != "refusal":
        logger.warning("Unexpected decisions answer type %r for %s", kind, name)
    return DecisionAnswer(name=name, type="refusal", refused=True)


def parse_answers(response: object, chunk: Sequence[DecisionQuestion]) -> dict[str, DecisionAnswer]:
    """Map response answers onto question names (missing -> refused)."""
    out: dict[str, DecisionAnswer] = {}
    for index, raw in enumerate(getattr(response, "answers", ()) or ()):
        name = getattr(raw, "name", None) or (chunk[index].name if index < len(chunk) else None)
        if isinstance(name, str):
            out[name] = _answer(raw, name)
    for question in chunk:
        if question.name not in out:
            out[question.name] = DecisionAnswer(name=question.name, type="refusal", refused=True)
    return out


def _usage(response: object) -> TokenUsage:
    usage = getattr(response, "usage", None)
    tokens = getattr(usage, "input_tokens", 0)
    details = getattr(usage, "input_tokens_details", None)
    cached = getattr(details, "cached_tokens", 0)
    return TokenUsage(
        input_tokens=tokens if isinstance(tokens, int) else 0,
        cached_input_tokens=cached if isinstance(cached, int) else 0,
    )


async def _one_request(
    spec: ModelSpec, input_text: str, chunk: list[DecisionQuestion],
    deadline: float | None, cost_tracker: CostTracker | None, task: str, role: str,
) -> tuple[dict[str, DecisionAnswer], TokenUsage, int]:
    payload = [q.to_api() for q in chunk]

    def run(api_key: str, timeout: float) -> object:
        return _sync_decisions({"model": spec.litellm_id, "input": input_text,
                                "questions": payload, "api_key": api_key, "timeout": timeout})

    start = time.perf_counter()
    try:
        response = await call_provider(run, provider=spec.provider, label=spec.id,
                                       timeout=spec.timeout_s or _DEFAULT_TIMEOUT_S,
                                       deadline=deadline)
    except LLMCallError as exc:
        if exc.is_hard:
            mark_unavailable(spec.id, f"{exc.kind}: {exc}")
        if cost_tracker is not None:
            cost_tracker.record_usage(spec, TokenUsage(), task, role, success=False)
        raise DecisionError(str(exc), exc.kind, spec.id) from exc
    latency = int((time.perf_counter() - start) * 1000)
    usage = _usage(response)
    try:
        answers = parse_answers(response, chunk)
    except (AttributeError, TypeError, ValueError) as exc:
        if cost_tracker is not None:  # the request was billed even if we cannot read it
            cost_tracker.record_usage(spec, usage, task, role, latency, success=False)
        raise DecisionError(f"unparseable decisions response: {short_error(exc)}",
                            "invalid_output", spec.id) from exc
    if cost_tracker is not None:
        cost_tracker.record_usage(spec, usage, task, role, latency)
    return answers, usage, latency


async def decide(
    input_text: str,
    questions: Sequence[DecisionQuestion],
    role: Role = "screen",
    cost_tracker: CostTracker | None = None,
    task: str = "screen",
    *,
    model: str | None = None,
    timeout: float | None = None,
) -> DecisionResult:
    """Ask predicate/choice questions about ``input_text``.

    Raises DecisionError when the role is disabled/unavailable, the questions
    are invalid, or the API fails after retries (caller skips the screen).
    """
    if not questions:
        raise DecisionError("no questions given", "bad_request")
    names = [q.name for q in questions]
    if len(set(names)) != len(names):
        raise DecisionError("question names must be unique", "bad_request")
    spec = spec_for(model, "decision") if model else resolve_role(role)
    try:
        if spec is None or spec.kind != "decision":
            raise DecisionError(f"no decisions model available for role '{role}'",
                                "unavailable", spec.id if spec else None)
        if cost_tracker is not None:
            cost_tracker.ensure_budget()
        deadline = deadline_from(timeout)
        parts = await asyncio.gather(*[
            _one_request(spec, input_text, chunk, deadline, cost_tracker, task, role)
            for chunk in _chunks(questions)
        ])
    except DecisionError as exc:
        if model is None:  # V5.8: an outage skips the screen; record why (risk-only layer)
            note_soft_failure(role, exc.model_id, exc.kind, str(exc)[:200], cost_tracker)
        raise
    result = DecisionResult(model=spec.id, requests=len(parts))
    usage = TokenUsage()
    for answers, part_usage, latency in parts:
        result.answers.update(answers)
        usage = usage + part_usage
        result.latency_ms = max(result.latency_ms, latency)
    result.input_tokens = usage.input_tokens
    result.cached_input_tokens = usage.cached_input_tokens
    result.cost_usd = compute_cost(spec, usage)
    return result
