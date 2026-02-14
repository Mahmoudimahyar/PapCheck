"""Unified LLM call wrapper using litellm.

Uses synchronous litellm.completion() in a thread pool to avoid
Windows event-loop issues with litellm's async httpx client.
"""

import json
import logging
import re
from typing import TypeVar

import litellm
from pydantic import BaseModel, ValidationError

from refcheck.llm.rate_limiter import call_with_rate_limit_retry
from refcheck.llm.templates import render_template

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_DEFAULT_MODEL = "anthropic/claude-sonnet-4-5-20250929"

# Pattern to strip markdown code fences from LLM responses
_CODE_FENCE_RE = re.compile(
    r"```(?:json)?\s*\n?(.*?)\n?\s*```",
    re.DOTALL,
)


def _clean_json_response(raw: str) -> str:
    """Strip markdown code fences and whitespace from LLM output."""
    text = raw.strip()
    match = _CODE_FENCE_RE.search(text)
    if match:
        text = match.group(1).strip()
    return text


def _sync_completion(
    model: str,
    messages: list[dict[str, str]],
) -> str:
    """Run litellm.completion synchronously (called from thread pool)."""
    response = litellm.completion(
        model=model,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    content: str | None = response.choices[0].message.content
    if not content:
        raise ValueError("Empty LLM response")
    result = str(content)
    logger.info(
        "LLM raw response len=%d first_char=%r first_50=%r",
        len(result), result[0] if result else "?", result[:50],
    )
    return result


async def call_llm(
    template: str,
    variables: dict[str, str],
    output_model: type[T],
    model: str = _DEFAULT_MODEL,
    max_retries: int = 1,
    use_cache: bool = True,
) -> T:
    """Call an LLM with a rendered prompt template and validate output.

    V3: Checks diskcache before calling the LLM. Caches valid responses.
    Retries on rate limits with exponential backoff (handled by
    rate_limiter module). Retries once on parse/validation failure.
    """
    # V3: Check cache first
    if use_cache:
        cached = _check_llm_cache(template, variables, model, output_model)
        if cached is not None:
            return cached

    prompt_text = render_template(template, variables)
    messages: list[dict[str, str]] = [
        {"role": "user", "content": prompt_text},
    ]

    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        raw_content = ""
        try:
            # V3: Rate-limit-aware call with exponential backoff
            raw_content = await call_with_rate_limit_retry(
                _sync_completion, model, messages,
            )
            content = _clean_json_response(raw_content)
            if not content:
                raise ValueError("Empty response after cleaning")
            parsed = json.loads(content)
            result = output_model.model_validate(parsed)
            logger.info(
                "LLM call succeeded: template=%s, attempt=%d",
                template, attempt + 1,
            )
            # V3: Cache the valid response
            if use_cache:
                _store_llm_cache(template, variables, model, content)
            return result

        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            last_error = exc
            preview = raw_content[:500] if raw_content else "<empty>"
            logger.warning(
                "LLM parse error (attempt %d): %s | raw[:%d]: %s",
                attempt + 1, exc, len(raw_content), preview,
            )
            if attempt < max_retries:
                messages.append({
                    "role": "user",
                    "content": (
                        f"Your response was invalid: {exc}. "
                        "Please return ONLY raw JSON with no "
                        "markdown formatting or code fences."
                    ),
                })

    raise LLMResponseInvalidError(
        f"Failed after {max_retries + 1} attempts: {last_error}"
    )


def _check_llm_cache(
    template: str,
    variables: dict[str, str],
    model: str,
    output_model: type[T],
) -> T | None:
    """Check the LLM cache for a matching response."""
    try:
        from refcheck.utils.cache import get_cached_llm_response

        cached_json = get_cached_llm_response(template, variables, model)
        if cached_json is None:
            return None
        parsed = json.loads(cached_json)
        result = output_model.model_validate(parsed)
        logger.info("LLM cache HIT: template=%s", template)
        return result
    except Exception:
        return None


def _store_llm_cache(
    template: str,
    variables: dict[str, str],
    model: str,
    response_json: str,
) -> None:
    """Store a valid LLM response in the cache."""
    try:
        from refcheck.utils.cache import cache_llm_response

        cache_llm_response(template, variables, model, response_json)
    except Exception:
        logger.debug("Failed to cache LLM response", exc_info=True)


class LLMResponseInvalidError(Exception):
    """LLM returned unparseable or schema-invalid output."""
