"""Multi-model LLM client: call one or many models in parallel."""

import asyncio
import logging
import time

import litellm
from pydantic import BaseModel

from refcheck.llm.cost_tracker import CostTracker
from refcheck.llm.json_parser import parse_json_response
from refcheck.llm.model_registry import ModelConfig

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 90


class ModelResponse(BaseModel):
    """Response from a single model call."""

    model: ModelConfig
    content: str
    parsed: dict[str, object] | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    response_time_ms: int = 0


def _sync_completion(
    model_id: str,
    messages: list[dict[str, str]],
    timeout: int,
    max_tokens: int,
) -> object:
    """Run litellm.completion synchronously (thread pool)."""
    return litellm.completion(
        model=model_id,
        messages=messages,
        temperature=0.1,
        timeout=timeout,
        max_tokens=max_tokens,
    )


async def call_model(
    model: ModelConfig,
    prompt: str,
    system_prompt: str = "",
    timeout: int = _DEFAULT_TIMEOUT,
    cost_tracker: CostTracker | None = None,
    task: str = "unknown",
) -> ModelResponse:
    """Call one model via litellm.completion() in asyncio.to_thread()."""
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    start = time.perf_counter()
    response = await asyncio.to_thread(
        _sync_completion,
        model.litellm_id,
        messages,
        timeout,
        model.max_output_tokens,
    )
    elapsed_ms = int((time.perf_counter() - start) * 1000)

    resp_obj = response  # litellm response is a dynamic object
    choices = getattr(resp_obj, "choices", [])
    content = str(getattr(choices[0].message, "content", "")) if choices else ""
    usage = getattr(resp_obj, "usage", None)
    input_tokens = getattr(usage, "prompt_tokens", 0) or 0
    output_tokens = getattr(usage, "completion_tokens", 0) or 0

    # Try to parse JSON
    parsed = None
    try:
        parsed = parse_json_response(content)
    except ValueError:
        logger.debug("Non-JSON response from %s", model.alias)

    if cost_tracker:
        cost_tracker.record(
            model, input_tokens, output_tokens,
            task, elapsed_ms,
        )

    return ModelResponse(
        model=model, content=content, parsed=parsed,
        input_tokens=input_tokens, output_tokens=output_tokens,
        response_time_ms=elapsed_ms,
    )


async def call_models_parallel(
    models: list[ModelConfig],
    prompt: str,
    system_prompt: str = "",
    timeout: int = _DEFAULT_TIMEOUT,
    cost_tracker: CostTracker | None = None,
    task: str = "unknown",
) -> list[ModelResponse]:
    """Call multiple models in parallel. Failed models logged, not fatal."""
    tasks = [
        _safe_call(m, prompt, system_prompt, timeout, cost_tracker, task)
        for m in models
    ]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]


async def _safe_call(
    model: ModelConfig,
    prompt: str,
    system_prompt: str,
    timeout: int,
    cost_tracker: CostTracker | None,
    task: str,
) -> ModelResponse | None:
    """Call a model, returning None on failure."""
    try:
        return await call_model(
            model, prompt, system_prompt, timeout, cost_tracker, task,
        )
    except Exception as exc:
        logger.warning(
            "Model %s failed: %s: %s",
            model.alias, type(exc).__name__, str(exc)[:200],
        )
        return None
