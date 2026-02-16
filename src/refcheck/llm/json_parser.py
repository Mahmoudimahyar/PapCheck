"""Parse JSON from LLM responses with multiple fallback strategies."""

import json
import re

# Matches markdown code fences
_CODE_FENCE_RE = re.compile(
    r"```(?:json)?\s*\n?(.*?)\n?\s*```",
    re.DOTALL,
)


def parse_json_response(raw: str) -> dict[str, object]:
    """Extract JSON dict from LLM response.

    Tries: direct parse, strip fences, find {...}, find [...].
    Raises ValueError if none work.
    """
    stripped = raw.strip()

    # Strategy 1: direct parse
    result = _try_parse(stripped)
    if isinstance(result, dict):
        return result

    # Strategy 2: strip markdown code fences
    fence_match = _CODE_FENCE_RE.search(stripped)
    if fence_match:
        result = _try_parse(fence_match.group(1).strip())
        if isinstance(result, dict):
            return result

    # Strategy 3: find first {...} block
    first_brace = stripped.find("{")
    last_brace = stripped.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        result = _try_parse(stripped[first_brace : last_brace + 1])
        if isinstance(result, dict):
            return result

    # Strategy 4: find first [...] block (array wrapping a dict)
    first_bracket = stripped.find("[")
    last_bracket = stripped.rfind("]")
    if first_bracket != -1 and last_bracket > first_bracket:
        arr = _try_parse(stripped[first_bracket : last_bracket + 1])
        if isinstance(arr, list) and arr and isinstance(arr[0], dict):
            first: dict[str, object] = arr[0]
            return first

    raise ValueError(f"Could not extract JSON from: {stripped[:200]}")


def _try_parse(text: str) -> dict[str, object] | list[object] | None:
    """Attempt JSON parse, returning None on failure."""
    try:
        result: dict[str, object] | list[object] = json.loads(text)
        return result
    except (json.JSONDecodeError, ValueError):
        return None
