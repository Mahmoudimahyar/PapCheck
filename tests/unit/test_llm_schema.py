"""Strict JSON schema generation and message/caching construction."""

from typing import Literal

from pydantic import BaseModel, Field

from refcheck.llm.messages import CACHE_BREAKPOINT, add_correction, build_messages
from refcheck.llm.model_registry import REGISTRY
from refcheck.llm.schema import response_format_for, schema_name, strict_json_schema


class EvidenceQuote(BaseModel):
    passage_id: str
    text: str = Field(max_length=400)
    role: Literal["supports", "contradicts", "closest"]


class JudgeLike(BaseModel):
    verdict: Literal["supported", "not_supported", "insufficient_evidence"]
    severity: Literal["none", "minor", "major"] = "none"
    confidence: float = Field(ge=0.0, le=1.0)
    quotes: list[EvidenceQuote] = Field(default_factory=list, max_length=3)
    explanation: str
    missing: str | None = None


class WithDict(BaseModel):
    scores: dict[str, float]


def _walk(node: object) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    if isinstance(node, dict):
        found.append(node)
        for value in node.values():
            found.extend(_walk(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_walk(item))
    return found


class TestStrictSchema:
    def test_objects_closed_and_all_fields_required(self) -> None:
        schema = strict_json_schema(JudgeLike)
        assert schema is not None
        objects = [n for n in _walk(schema) if n.get("type") == "object"]
        assert len(objects) == 2  # JudgeLike + inlined EvidenceQuote
        for obj in objects:
            assert obj["additionalProperties"] is False
            props = obj["properties"]
            assert isinstance(props, dict) and obj["required"] == list(props)

    def test_refs_inlined_and_unsupported_keywords_removed(self) -> None:
        schema = strict_json_schema(JudgeLike)
        nodes = _walk(schema)
        for banned in ("$ref", "$defs", "default", "maximum", "minimum", "maxLength",
                       "maxItems", "title"):
            assert not any(banned in n for n in nodes), banned

    def test_nullable_field_kept_as_any_of(self) -> None:
        schema = strict_json_schema(JudgeLike)
        assert schema is not None
        missing = schema["properties"]["missing"]  # type: ignore[index]
        assert {"type": "null"} in missing["anyOf"]

    def test_property_named_like_a_keyword_survives(self) -> None:
        class Odd(BaseModel):
            title: str
            default: int

        schema = strict_json_schema(Odd)
        assert schema is not None
        props = schema["properties"]
        assert isinstance(props, dict) and set(props) == {"title", "default"}

    def test_dict_field_is_not_strict(self) -> None:
        assert strict_json_schema(WithDict) is None

    def test_schema_name_is_sanitized(self) -> None:
        assert schema_name(JudgeLike) == "JudgeLike"


class TestResponseFormat:
    def test_strict_for_openai_and_anthropic(self) -> None:
        for model_id in ("gpt-6-luna", "claude-sonnet-5-5"):
            fmt = response_format_for(REGISTRY[model_id], JudgeLike)
            assert fmt is not None and fmt["type"] == "json_schema"

    def test_non_strict_model_falls_back(self) -> None:
        assert response_format_for(REGISTRY["gpt-6-luna"], WithDict) == {"type": "json_object"}
        assert response_format_for(REGISTRY["claude-haiku-5-5"], WithDict) is None


class TestMessages:
    def test_anthropic_user_prefix_breakpoint(self) -> None:
        text = f"PASSAGES...\n{CACHE_BREAKPOINT}\nCLAIM: x"
        messages = build_messages(text, None, "anthropic")
        assert len(messages) == 1
        blocks = messages[0]["content"]
        assert isinstance(blocks, list) and len(blocks) == 2
        assert blocks[0]["cache_control"] == {"type": "ephemeral"}
        assert "cache_control" not in blocks[1]

    def test_anthropic_breakpoints_capped_at_four(self) -> None:
        text = CACHE_BREAKPOINT.join(f"part {i}" for i in range(7))
        messages = build_messages(text, "SYSTEM", "anthropic")
        user_blocks = messages[1]["content"]
        assert isinstance(user_blocks, list)
        marked = sum("cache_control" in b for b in user_blocks) + 1  # + system block
        assert marked == 4

    def test_openai_marker_removed(self) -> None:
        messages = build_messages(f"A\n{CACHE_BREAKPOINT}\nB", f"S{CACHE_BREAKPOINT}", "openai")
        assert messages[0] == {"role": "system", "content": "S"}
        content = messages[1]["content"]
        assert isinstance(content, str) and CACHE_BREAKPOINT not in content
        assert "A" in content and "B" in content

    def test_add_correction(self) -> None:
        out = add_correction([{"role": "user", "content": "q"}], "", "fix it")
        assert [m["role"] for m in out] == ["user", "assistant", "user"]
        assert out[1]["content"] == "(empty reply)"
