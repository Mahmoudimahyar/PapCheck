"""Build provider response_format payloads from Pydantic models.

Strict JSON schema works for OpenAI and Anthropic (via litellm's
response_format). Strict mode needs every object closed
(additionalProperties false) with all properties required, and no
unsupported keywords — so constraints are stripped here and enforced by
Pydantic validation afterwards. Models that cannot be expressed strictly
(free-form dicts, recursion) fall back to json_object / prompt-only JSON.
"""

import re

from pydantic import BaseModel

from refcheck.llm.model_spec import ModelSpec

JsonDict = dict[str, object]

_DROP_KEYS = frozenset({
    "default", "title", "examples", "minimum", "maximum", "exclusiveMinimum",
    "exclusiveMaximum", "multipleOf", "minLength", "maxLength", "pattern", "format",
    "minItems", "maxItems", "uniqueItems", "discriminator", "minProperties",
    "maxProperties",
})
_MAX_DEPTH = 12


class _NotStrictError(Exception):
    """Raised internally when a schema cannot be made strict."""


def _resolve(node: object, defs: JsonDict, depth: int) -> object:
    if depth > _MAX_DEPTH:
        raise _NotStrictError("schema too deep or recursive")
    if isinstance(node, list):
        return [_resolve(item, defs, depth + 1) for item in node]
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if isinstance(ref, str):
        target = defs.get(ref.rsplit("/", 1)[-1])
        if target is None:
            raise _NotStrictError(f"unresolvable $ref {ref}")
        return _resolve(target, defs, depth + 1)
    out: JsonDict = {}
    for key, value in node.items():
        if key in _DROP_KEYS or key == "$defs":
            continue
        if key == "properties" and isinstance(value, dict):
            out[key] = {name: _resolve(sub, defs, depth + 1) for name, sub in value.items()}
        else:
            out[key] = _resolve(value, defs, depth + 1)
    if out.get("type") == "object" or "properties" in out:
        extra = out.get("additionalProperties")
        if extra not in (None, False):
            raise _NotStrictError("free-form object (dict field)")
        props = out.get("properties")
        if not isinstance(props, dict) or not props:
            raise _NotStrictError("object without properties")
        out["additionalProperties"] = False
        out["required"] = list(props)
    return out


def strict_json_schema(model: type[BaseModel]) -> JsonDict | None:
    """Strict-mode JSON schema for a Pydantic model, or None if impossible."""
    raw = model.model_json_schema()
    defs = raw.get("$defs")
    try:
        resolved = _resolve(raw, defs if isinstance(defs, dict) else {}, 0)
    except _NotStrictError:
        return None
    return resolved if isinstance(resolved, dict) else None


def schema_name(model: type[BaseModel]) -> str:
    """Provider-safe schema name (letters, digits, _ and -; max 64)."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", model.__name__)[:64] or "output"


def response_format_for(spec: ModelSpec, model: type[BaseModel]) -> JsonDict | None:
    """response_format for litellm, or None to rely on prompt-only JSON.

    Anthropic has no plain JSON mode in litellm without tools (which crash
    without the mcp package), so non-strict models get no response_format.
    """
    schema = strict_json_schema(model) if spec.supports_json_schema else None
    if schema is not None:
        return {
            "type": "json_schema",
            "json_schema": {"name": schema_name(model), "schema": schema, "strict": True},
        }
    if spec.provider == "anthropic":
        return None
    return {"type": "json_object"}
