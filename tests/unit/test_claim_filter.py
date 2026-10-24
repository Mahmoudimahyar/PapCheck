"""Tests for empty claim filtering (Bug Fix 4)."""

from refcheck.models.claim import Claim
from refcheck.stages.detect_citations.claim_filter import (
    filter_empty_claims,
    strip_citation_markers,
)


def _make_claim(
    claim_id: int = 1,
    text: str = "",
    extracted: str = "",
) -> Claim:
    return Claim(
        id=claim_id,
        manuscript_text=text,
        extracted_claim=extracted or text,
        reference_ids=[1],
    )


class TestStripCitationMarkers:
    """Remove citation markers from text."""

    def test_strips_author_year(self) -> None:
        text = "(Lane et al., 2020; Fenn-Ashby et al., 2022)"
        result = strip_citation_markers(text)
        assert result == ""

    def test_strips_numbered_citations(self) -> None:
        text = "This is well established [15,16]."
        result = strip_citation_markers(text)
        assert "established" in result

    def test_preserves_normal_text(self) -> None:
        text = "Hydrogels promote tissue regeneration."
        result = strip_citation_markers(text)
        assert result == text

    def test_strips_inline_author_year(self) -> None:
        text = "This has been studied (Smith et al., 2021)."
        result = strip_citation_markers(text)
        assert "studied" in result
        assert "Smith" not in result

    def test_strips_multiple_numbered_refs(self) -> None:
        text = "As shown previously [1-3, 5]."
        result = strip_citation_markers(text)
        assert "shown" in result


class TestFilterEmptyClaims:
    """Filter out citation-only claims."""

    def test_filters_citation_only_text(self) -> None:
        claims = [
            _make_claim(
                claim_id=1,
                text="(Lane et al., 2020; Fenn-Ashby et al., 2022)",
            ),
            _make_claim(
                claim_id=2,
                text="Hydrogels promote tissue regeneration (Smith et al., 2021).",
            ),
        ]
        result = filter_empty_claims(claims)
        assert len(result) == 1
        assert result[0].id == 2

    def test_keeps_short_but_real_claims(self) -> None:
        claims = [
            _make_claim(
                claim_id=1,
                text="This is well established [15,16].",
            ),
        ]
        result = filter_empty_claims(claims)
        assert len(result) == 1

    def test_filters_empty_string(self) -> None:
        claims = [_make_claim(claim_id=1, text="")]
        result = filter_empty_claims(claims)
        assert len(result) == 0

    def test_keeps_normal_claims(self) -> None:
        claims = [
            _make_claim(
                claim_id=1,
                text="Drug X reduced mortality by 30% in elderly patients.",
            ),
        ]
        result = filter_empty_claims(claims)
        assert len(result) == 1

    def test_handles_empty_list(self) -> None:
        result = filter_empty_claims([])
        assert result == []

    def test_filters_whitespace_only(self) -> None:
        claims = [_make_claim(claim_id=1, text="   ")]
        result = filter_empty_claims(claims)
        assert len(result) == 0
