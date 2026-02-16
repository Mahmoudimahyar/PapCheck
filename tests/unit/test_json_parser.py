"""Tests for JSON parser with multiple strategies."""

import pytest

from refcheck.llm.json_parser import parse_json_response


class TestDirectParse:
    """Strategy 1: direct JSON parse."""

    def test_valid_json_object(self) -> None:
        result = parse_json_response('{"verdict": "supported", "confidence": 0.9}')
        assert result["verdict"] == "supported"
        assert result["confidence"] == 0.9

    def test_json_with_whitespace(self) -> None:
        result = parse_json_response('  {"key": "value"}  ')
        assert result["key"] == "value"


class TestStripFences:
    """Strategy 2: strip markdown code fences."""

    def test_json_in_code_fence(self) -> None:
        text = '```json\n{"verdict": "supported"}\n```'
        result = parse_json_response(text)
        assert result["verdict"] == "supported"

    def test_code_fence_no_language(self) -> None:
        text = '```\n{"verdict": "not_supported"}\n```'
        result = parse_json_response(text)
        assert result["verdict"] == "not_supported"


class TestFindBraces:
    """Strategy 3: find first {...} block."""

    def test_json_with_surrounding_text(self) -> None:
        text = 'Here is my analysis:\n{"verdict": "supported"}\nDone.'
        result = parse_json_response(text)
        assert result["verdict"] == "supported"

    def test_json_with_prefix_text(self) -> None:
        text = 'The result is {"confidence": 0.85, "verdict": "supported"}'
        result = parse_json_response(text)
        assert result["confidence"] == 0.85


class TestFindBrackets:
    """Strategy 4: find [...] block wrapping a dict."""

    def test_array_with_dict(self) -> None:
        text = '[{"verdict": "contradicted"}]'
        result = parse_json_response(text)
        assert result["verdict"] == "contradicted"


class TestFailure:
    """Ensure ValueError on unparseable input."""

    def test_no_json_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Could not extract JSON"):
            parse_json_response("This is plain text with no JSON.")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_json_response("")
