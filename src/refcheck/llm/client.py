"""Unified LLM call wrapper using litellm.

Uses synchronous litellm.completion() in a thread pool to avoid
Windows event-loop issues with litellm's async httpx client.
"""

import json
import logging
import os
import traceback
from typing import TypeVar

import litellm
from pydantic import BaseModel, ValidationError

from refcheck.llm.cache import check_llm_cache, store_llm_cache
from refcheck.llm.json_extractor import extract_json_from_response
from refcheck.llm.key_manager import rotate_anthropic_key
from refcheck.llm.rate_limiter import call_with_rate_limit_retry
from refcheck.llm.templates import render_template

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_DEFAULT_MODEL = "anthropic/claude-sonnet-4-5-20250929"
_DEFAULT_TIMEOUT = 120


def _is_billing_error(exc: Exception) -> bool:
    """Check if an exception is a billing/credit exhaustion error."""
    msg = str(exc).lower()
    return "credit balance" in msg or "billing" in msg


def _sync_completion(
    model: str,
    messages: list[dict[str, str]],
) -> str:
    """Run litellm.completion synchronously (called via thread pool).

    On billing/credit errors, rotates to the backup Anthropic API key
    and retries once automatically.
    """
    try:
        return _do_completion(model, messages)
    except Exception as exc:
        if _is_billing_error(exc) and "anthropic" in model.lower():
            new_key = rotate_anthropic_key()
            if new_key:
                logger.warning(
                    "Anthropic credit exhausted, rotating to backup key",
                )
                os.environ["ANTHROPIC_API_KEY"] = new_key
                return _do_completion(model, messages)
        raise


def _do_completion(
    model: str,
    messages: list[dict[str, str]],
) -> str:
    """Execute a single litellm.completion call."""
    response = litellm.completion(
        model=model,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.1,
        timeout=_DEFAULT_TIMEOUT,
    )
    content: str | None = response.choices[0].message.content
    if not content:
        raise ValueError("Empty LLM response")
    result = str(content)
    logger.info("LLM raw len=%d first_50=%r", len(result), result[:50])
    return result


async def call_llm(
    template: str,
    variables: dict[str, str],
    output_model: type[T],
    model: str = _DEFAULT_MODEL,
    max_retries: int = 1,
    use_cache: bool = True,
) -> T:
    """Call LLM with rendered prompt, validate output via Pydantic.

    V4: Robust JSON extraction. Handles code fences, surrounding
    text, partial JSON. Caches valid responses. Retries on parse
    failures and rate limits with exponential backoff.
    """
    if use_cache:
        cached = check_llm_cache(template, variables, model, output_model)
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
            raw_content = await call_with_rate_limit_retry(
                _sync_completion, model, messages,
            )
            content = extract_json_from_response(raw_content)
            if not content:
                raise ValueError("Empty response after extraction")
            parsed = json.loads(content)
            result = output_model.model_validate(parsed)
            logger.info(
                "LLM OK: template=%s attempt=%d", template, attempt + 1,
            )
            if use_cache:
                store_llm_cache(template, variables, model, content)
            return result

        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            last_error = exc
            preview = raw_content[:500] if raw_content else "<empty>"
            logger.warning(
                "LLM parse error (%d/%d): %s: %s | raw: %s",
                attempt + 1, max_retries + 1,
                type(exc).__name__, exc, preview,
            )
            if attempt < max_retries:
                messages.append({
                    "role": "user",
                    "content": (
                        f"Your response was invalid: {exc}. "
                        "Return ONLY raw JSON, no markdown."
                    ),
                })
        except Exception as exc:
            logger.error(
                "LLM call error (%d/%d): %s: %s\n%s",
                attempt + 1, max_retries + 1,
                type(exc).__name__, exc, traceback.format_exc(),
            )
            raise

    raise LLMResponseInvalidError(
        f"Failed after {max_retries + 1} attempts: {last_error}"
    )


class LLMResponseInvalidError(Exception):
    """LLM returned unparseable or schema-invalid output."""
