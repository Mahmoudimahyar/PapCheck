"""Robust JSON extraction from LLM responses."""

import json
import re

# Pattern to strip markdown code fences from LLM responses
_CODE_FENCE_RE = re.compile(
    r"```(?:json)?\s*\n?(.*?)\n?\s*```",
    re.DOTALL,
)


def extract_json_from_response(text: str) -> str:
    """Extract JSON from LLM response, handling fences and text.

    Tries multiple strategies in order:
    1. Direct parse (already valid JSON)
    2. Strip markdown code fences
    3. Find first { to last }
    4. Find first [ to last ]
    """
    stripped = text.strip()

    # Strategy 1: direct parse
    try:
        json.loads(stripped)
        return stripped
    except (json.JSONDecodeError, ValueError):
        pass

    # Strategy 2: strip code fences
    fence_match = _CODE_FENCE_RE.search(stripped)
    if fence_match:
        inner = fence_match.group(1).strip()
        try:
            json.loads(inner)
            return inner
        except (json.JSONDecodeError, ValueError):
            pass

    # Strategy 3: find first { to last }
    first_brace = stripped.find("{")
    last_brace = stripped.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        candidate = stripped[first_brace:last_brace + 1]
        try:
            json.loads(candidate)
            return candidate
        except (json.JSONDecodeError, ValueError):
            pass

    # Strategy 4: find first [ to last ]
    first_bracket = stripped.find("[")
    last_bracket = stripped.rfind("]")
    if first_bracket != -1 and last_bracket > first_bracket:
        candidate = stripped[first_bracket:last_bracket + 1]
        try:
            json.loads(candidate)
            return candidate
        except (json.JSONDecodeError, ValueError):
            pass

    # Nothing worked — return stripped for caller to handle
    return stripped
