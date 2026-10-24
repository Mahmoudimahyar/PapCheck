"""Token usage extraction and cost computation."""

from pydantic import BaseModel

from refcheck.llm.model_spec import ModelSpec


class TokenUsage(BaseModel):
    """Token counts for one or more calls.

    ``input_tokens`` is the TOTAL prompt size, including cached reads and
    cache writes (litellm reports Anthropic prompt_tokens that way too).
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
        )


def _int(obj: object, name: str) -> int:
    value = obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)
    return int(value) if isinstance(value, (int, float)) else 0


def usage_from_response(response: object) -> TokenUsage:
    """Read usage from a litellm chat/embedding response (missing -> 0)."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return TokenUsage()
    prompt_details = getattr(usage, "prompt_tokens_details", None)
    completion_details = getattr(usage, "completion_tokens_details", None)
    cached = _int(usage, "cache_read_input_tokens") or _int(prompt_details, "cached_tokens")
    return TokenUsage(
        input_tokens=_int(usage, "prompt_tokens"),
        output_tokens=_int(usage, "completion_tokens"),
        cached_input_tokens=cached,
        cache_write_tokens=_int(usage, "cache_creation_input_tokens"),
        reasoning_tokens=_int(completion_details, "reasoning_tokens"),
    )


def compute_cost(spec: ModelSpec, usage: TokenUsage) -> float:
    """USD cost of a call from registry prices (cached tokens discounted)."""
    cached_rate = spec.cached_input_cost_per_m
    write_rate = spec.cache_write_cost_per_m
    cached = min(usage.cached_input_tokens, usage.input_tokens)
    written = min(usage.cache_write_tokens, usage.input_tokens - cached)
    fresh = usage.input_tokens - cached - written
    cost = (
        fresh * spec.input_cost_per_m
        + cached * (spec.input_cost_per_m if cached_rate is None else cached_rate)
        + written * (spec.input_cost_per_m if write_rate is None else write_rate)
        + usage.output_tokens * spec.output_cost_per_m
    )
    return cost / 1_000_000
