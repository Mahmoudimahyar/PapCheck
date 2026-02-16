"""Tests for citation detection data models (V4)."""

from refcheck.models.citation import (
    CitationInstance,
    MissingCitation,
    VerificationUnit,
)


class TestCitationInstance:
    def test_author_year_parenthetical(self) -> None:
        c = CitationInstance(
            raw_marker="(Smith et al., 2020)",
            style="author_year_parenthetical",
            paragraph_index=0,
            char_start=10,
            char_end=30,
            authors=["Smith"],
            year="2020",
        )
        assert c.authors == ["Smith"]
        assert c.year == "2020"
        assert c.style == "author_year_parenthetical"

    def test_numbered_bracket(self) -> None:
        c = CitationInstance(
            raw_marker="[7]",
            style="numbered_bracket",
            paragraph_index=1,
            char_start=5,
            char_end=8,
            number=7,
        )
        assert c.number == 7
        assert c.authors == []

    def test_narrative_flag(self) -> None:
        c = CitationInstance(
            raw_marker="Smith et al. (2020)",
            style="author_year_narrative",
            paragraph_index=0,
            char_start=0,
            char_end=19,
            is_narrative=True,
            authors=["Smith"],
            year="2020",
        )
        assert c.is_narrative is True

    def test_reference_mapping_defaults(self) -> None:
        c = CitationInstance(
            raw_marker="[1]",
            style="numbered_bracket",
            paragraph_index=0,
            char_start=0,
            char_end=3,
        )
        assert c.reference_id is None
        assert c.mapping_confidence == 0.0
        assert c.mapping_method == ""


class TestVerificationUnit:
    def test_backward_compat_extracted_claim(self) -> None:
        vu = VerificationUnit(
            manuscript_text="Full sentence here.",
            scope_text="specific scope",
            citation_marker="(Smith, 2020)",
            reference_id=5,
        )
        assert vu.extracted_claim == "specific scope"

    def test_backward_compat_reference_ids(self) -> None:
        vu = VerificationUnit(
            manuscript_text="Sentence",
            scope_text="Scope",
            citation_marker="[7]",
            reference_id=7,
        )
        assert vu.reference_ids == [7]

    def test_claim_type_default(self) -> None:
        vu = VerificationUnit(
            manuscript_text="Test",
            scope_text="Test",
            citation_marker="[1]",
            reference_id=1,
        )
        assert vu.claim_type == "factual"
        assert vu.priority == "medium"

    def test_all_fields_populated(self) -> None:
        vu = VerificationUnit(
            id=42,
            manuscript_text="Full sentence (Smith, 2020).",
            scope_text="Full sentence",
            citation_marker="(Smith, 2020)",
            paragraph_index=3,
            char_start=0,
            char_end=27,
            section_heading="Results",
            reference_id=10,
            reference_title="A Great Paper",
            reference_authors=["Smith", "Jones"],
            citation_style="author_year_parenthetical",
            is_narrative=False,
            claim_type="factual",
            priority="high",
        )
        assert vu.id == 42
        assert vu.reference_title == "A Great Paper"


class TestMissingCitation:
    def test_basic_creation(self) -> None:
        mc = MissingCitation(
            sentence_text="30% of patients experience complications",
            paragraph_index=5,
            confidence=0.85,
            category="statistical_claim",
            reason="Contains percentage without source",
        )
        assert mc.confidence == 0.85
        assert mc.category == "statistical_claim"

    def test_defaults(self) -> None:
        mc = MissingCitation(
            sentence_text="Some text",
            paragraph_index=0,
        )
        assert mc.id == 0
        assert mc.char_start == 0
        assert mc.suggestion == ""
