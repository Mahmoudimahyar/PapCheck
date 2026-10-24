"""Tests for second-pass title repair (heuristic + LLM batch)."""

from unittest.mock import AsyncMock, patch

import pytest

from refcheck.models.reference import Reference
from refcheck.stages.parse_docx.title_repairer import (
    detect_and_repair_bad_titles,
    extract_title_from_raw_text,
    is_likely_bad_title,
)


def _make_ref(
    ref_id: int = 1,
    title: str = "Short",
    raw_text: str = "",
) -> Reference:
    return Reference(id=ref_id, title=title, raw_text=raw_text)


class TestIsLikelyBadTitle:
    """Detect titles that are journal abbreviations or garbage."""

    def test_detects_journal_abbrev(self) -> None:
        assert is_likely_bad_title("Front") is True
        assert is_likely_bad_title("Orthop") is True
        assert is_likely_bad_title("Int") is True
        assert is_likely_bad_title("Sci") is True

    def test_detects_doi_as_bad_title(self) -> None:
        assert is_likely_bad_title("doi: 10.5555/jsm.a.30001") is True

    def test_detects_bare_doi_as_bad(self) -> None:
        assert is_likely_bad_title("10.1016/j.biomaterials.2020") is True

    def test_detects_year_fragment(self) -> None:
        assert is_likely_bad_title("(2023b)") is True

    def test_detects_empty_title(self) -> None:
        assert is_likely_bad_title("") is True
        assert is_likely_bad_title("   ") is True

    def test_detects_short_title(self) -> None:
        assert is_likely_bad_title("Short title") is True

    def test_accepts_normal_title(self) -> None:
        title = "Hydrogel scaffolds for tissue engineering applications"
        assert is_likely_bad_title(title) is False

    def test_accepts_long_title(self) -> None:
        title = "Injectable hydrogel scaffolds promote bone regeneration in vivo"
        assert is_likely_bad_title(title) is False


class TestExtractTitleFromRawText:
    """Extract real titles from raw reference text."""

    def test_extracts_from_standard_format(self) -> None:
        raw = (
            "Bai, J. et al. (2024). Injectable hydrogel scaffolds "
            "promote bone regeneration. Frontiers in Bioengineering, "
            "12, 1234-1240."
        )
        title = extract_title_from_raw_text(raw)
        assert title is not None
        assert len(title) > 25

    def test_returns_none_for_empty(self) -> None:
        assert extract_title_from_raw_text("") is None
        assert extract_title_from_raw_text("   ") is None

    def test_skips_doi_segments(self) -> None:
        raw = "doi: 10.5555/jsm.a.30001. Smith, J. et al."
        title = extract_title_from_raw_text(raw)
        if title is not None:
            assert not title.startswith("doi:")

    def test_skips_url_segments(self) -> None:
        raw = "https://example.com/paper.pdf. Some other text here."
        title = extract_title_from_raw_text(raw)
        if title is not None:
            assert not title.startswith("http")


class TestDetectAndRepairBadTitles:
    """Integration of heuristic title repair."""

    def test_repairs_from_raw_text(self) -> None:
        ref = _make_ref(
            title="Front",
            raw_text=(
                "Bai, J. et al. (2024). Injectable hydrogel scaffolds "
                "promote bone regeneration in rats. Frontiers in "
                "Bioengineering, 12, 1234-1240."
            ),
        )
        refs = [ref]
        detect_and_repair_bad_titles(refs)
        # List item should be replaced with repaired copy
        assert refs[0].repair_applied == "title_re_extracted"
        assert len(refs[0].title) > 25

    def test_flags_unrepairable_for_llm(self) -> None:
        ref = _make_ref(title="Int", raw_text="Int")
        needs_llm = detect_and_repair_bad_titles([ref])
        assert len(needs_llm) == 1
        assert needs_llm[0][1] is ref

    def test_skips_good_titles(self) -> None:
        ref = _make_ref(
            title="Hydrogel scaffolds for tissue engineering applications",
        )
        needs_llm = detect_and_repair_bad_titles([ref])
        assert len(needs_llm) == 0
        assert ref.repair_applied == "none"


class TestBatchRepairTitles:
    """LLM batch title repair (mocked)."""

    @pytest.mark.asyncio
    async def test_batch_repair_returns_titles(self) -> None:
        from refcheck.stages.parse_docx.title_llm_repair import (
            TitleRepairItem,
            TitleRepairResponse,
            batch_repair_titles,
        )

        mock_response = TitleRepairResponse(repairs=[
            TitleRepairItem(index=0, title="Corrected paper title about hydrogels and scaffolds"),
        ])

        ref = _make_ref(title="Front", raw_text="Front...")

        with patch(
            "refcheck.stages.parse_docx.title_llm_repair.call_llm",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await batch_repair_titles([(0, ref)])

        assert 0 in result
        assert "hydrogel" in result[0].lower()

    @pytest.mark.asyncio
    async def test_batch_repair_handles_llm_failure(self) -> None:
        from refcheck.stages.parse_docx.title_llm_repair import batch_repair_titles

        ref = _make_ref(title="Int", raw_text="Int...")

        with patch(
            "refcheck.stages.parse_docx.title_llm_repair.call_llm",
            new_callable=AsyncMock,
            side_effect=RuntimeError("LLM unavailable"),
        ):
            result = await batch_repair_titles([(0, ref)])

        assert result == {}

    @pytest.mark.asyncio
    async def test_batch_repair_empty_input(self) -> None:
        from refcheck.stages.parse_docx.title_llm_repair import batch_repair_titles

        result = await batch_repair_titles([])
        assert result == {}


def test_surname_comma_initials_author_list_is_not_a_title() -> None:
    """Author lists like 'Zane, Q., Garnier-Gaspard, C.' must not win as titles."""
    from refcheck.stages.parse_docx.title_repairer import extract_title_from_raw_text

    raw = (
        "Zane, Q., Garnier-Gaspard, C., Ives, Y., Gale, Z., Girard-Lemoine, S., "
        "Wade, Y., Bauer, L. (2022). Cell Encapsulation: New Designs for "
        "Synthetic Grafts. Front. Synth. 13, 100001."
    )
    assert extract_title_from_raw_text(raw) == (
        "Cell Encapsulation: New Designs for Synthetic Grafts"
    )
