"""Tests for paragraph_text field propagation through models, DB, and pipeline.

Covers the full lifecycle: model declaration, attribute assignment, model_copy
(used by compound_splitter), detection pipeline output, scope resolution,
claim conversion, and DB round-trip.
"""

import pytest

from refcheck.models.citation import CitationInstance, VerificationUnit
from refcheck.models.claim import Claim
from refcheck.models.reference import ManuscriptSection, ParsedManuscript


class TestClaimParagraphText:
    """paragraph_text field on Claim model."""

    def test_claim_has_paragraph_text_field(self) -> None:
        claim = Claim(
            id=1,
            manuscript_text="Short sentence.",
            paragraph_text="Full paragraph with more context around the sentence.",
            extracted_claim="Short sentence.",
            reference_ids=[1],
        )
        assert claim.paragraph_text == (
            "Full paragraph with more context around the sentence."
        )

    def test_claim_paragraph_text_defaults_empty(self) -> None:
        claim = Claim(id=1, reference_ids=[1])
        assert claim.paragraph_text == ""


class TestCitationInstanceParagraphText:
    """paragraph_text field on CitationInstance."""

    def test_citation_has_paragraph_text(self) -> None:
        cit = CitationInstance(
            raw_marker="(Smith, 2020)",
            paragraph_index=0,
            char_start=50,
            char_end=65,
            sentence_text="Drug X works (Smith, 2020).",
            paragraph_text="Full paragraph about Drug X. Drug X works (Smith, 2020).",
            style="author_year_parenthetical",
        )
        assert "Full paragraph" in cit.paragraph_text

    def test_citation_paragraph_text_defaults_empty(self) -> None:
        cit = CitationInstance(
            raw_marker="[1]",
            paragraph_index=0,
            char_start=10,
            char_end=13,
            style="numbered_bracket",
        )
        assert cit.paragraph_text == ""

    def test_paragraph_text_field_in_model_fields(self) -> None:
        """Ensure paragraph_text is declared in model_fields (not just extra)."""
        assert "paragraph_text" in CitationInstance.model_fields

    def test_paragraph_text_attribute_assignment(self) -> None:
        """Direct attribute assignment on CitationInstance works."""
        cit = CitationInstance(
            raw_marker="[1]",
            style="numbered_bracket",
            paragraph_index=0,
            char_start=0,
            char_end=3,
        )
        cit.paragraph_text = "assigned paragraph"
        assert cit.paragraph_text == "assigned paragraph"

    def test_paragraph_text_survives_model_copy(self) -> None:
        """model_copy preserves paragraph_text (compound_splitter pattern)."""
        cit = CitationInstance(
            raw_marker="[1-3]",
            style="numbered_bracket",
            paragraph_index=0,
            char_start=10,
            char_end=15,
            paragraph_text="original paragraph text",
        )
        copied = cit.model_copy(update={"number": 1, "raw_marker": "[1]"})
        assert copied.paragraph_text == "original paragraph text"

    def test_paragraph_text_assignable_after_model_copy(self) -> None:
        """After model_copy, paragraph_text can still be assigned."""
        cit = CitationInstance(
            raw_marker="[1-3]",
            style="numbered_bracket",
            paragraph_index=0,
            char_start=10,
            char_end=15,
        )
        copied = cit.model_copy(update={"number": 2, "raw_marker": "[2]"})
        copied.paragraph_text = "new paragraph after copy"
        assert copied.paragraph_text == "new paragraph after copy"


class TestVerificationUnitParagraphText:
    """paragraph_text on VerificationUnit."""

    def test_unit_has_paragraph_text(self) -> None:
        unit = VerificationUnit(
            manuscript_text="Sentence text",
            paragraph_text="Full paragraph text around the sentence",
            scope_text="Sentence text",
            citation_marker="[1]",
            paragraph_index=0,
            char_start=0,
            char_end=10,
            section_heading="Introduction",
            reference_id=1,
        )
        assert unit.paragraph_text == "Full paragraph text around the sentence"


class TestClaimDBRoundTrip:
    """paragraph_text persists through DB conversion."""

    def test_claim_to_db_includes_paragraph_text(self) -> None:
        from refcheck.db.converters import claim_to_db

        claim = Claim(
            id=1,
            manuscript_text="sentence",
            paragraph_text="full paragraph",
            extracted_claim="sentence",
            reference_ids=[1],
        )
        db_row = claim_to_db(claim, "test-session")
        assert db_row.paragraph_text == "full paragraph"

    def test_db_to_claim_includes_paragraph_text(self) -> None:
        from refcheck.db.converters import claim_to_db, db_to_claim

        claim = Claim(
            id=2,
            manuscript_text="sentence",
            paragraph_text="the full paragraph context",
            extracted_claim="sentence",
            reference_ids=[1],
        )
        db_row = claim_to_db(claim, "test-session")
        restored = db_to_claim(db_row)
        assert restored.paragraph_text == "the full paragraph context"


class TestDetectAllCitationsParagraphText:
    """End-to-end: detect_all_citations sets paragraph_text on every citation."""

    @pytest.fixture()
    def manuscript(self) -> ParsedManuscript:
        return ParsedManuscript(
            filename="test.docx",
            sections=[
                ManuscriptSection(
                    heading="Introduction",
                    text=(
                        "Hydrogels are widely used in tissue engineering "
                        "(Smith et al., 2020). These materials show excellent "
                        "biocompatibility (Wang et al., 2021)."
                    ),
                ),
                ManuscriptSection(
                    heading="Methods",
                    text=(
                        "We used a modified protocol described by "
                        "Smith et al. (2020) for hydrogel synthesis."
                    ),
                ),
            ],
        )

    def test_all_citations_have_paragraph_text(
        self, manuscript: ParsedManuscript,
    ) -> None:
        from refcheck.stages.detect_citations import detect_all_citations

        citations = detect_all_citations(manuscript)
        assert len(citations) > 0
        for cit in citations:
            assert cit.paragraph_text != "", (
                f"Citation {cit.raw_marker} missing paragraph_text"
            )

    def test_paragraph_text_contains_citation_marker(
        self, manuscript: ParsedManuscript,
    ) -> None:
        from refcheck.stages.detect_citations import detect_all_citations

        citations = detect_all_citations(manuscript)
        for cit in citations:
            assert cit.raw_marker in cit.paragraph_text or (
                cit.raw_marker.strip("()") in cit.paragraph_text
            ), (
                f"paragraph_text should contain the citation marker "
                f"{cit.raw_marker!r}"
            )

    def test_paragraph_text_matches_section(
        self, manuscript: ParsedManuscript,
    ) -> None:
        """paragraph_text for each citation should come from correct section."""
        from refcheck.stages.detect_citations import detect_all_citations

        citations = detect_all_citations(manuscript)
        for cit in citations:
            if "protocol" in cit.paragraph_text.lower():
                assert cit.section_heading == "Methods"
            elif "widely used" in cit.paragraph_text.lower():
                assert cit.section_heading == "Introduction"


class TestScopeResolverParagraphText:
    """resolve_scopes propagates paragraph_text to VerificationUnit."""

    def test_scope_resolver_carries_paragraph_text(self) -> None:
        from refcheck.stages.detect_citations.scope_resolver import (
            resolve_scopes,
        )

        cit = CitationInstance(
            id=1,
            raw_marker="[1]",
            style="numbered_bracket",
            paragraph_index=0,
            char_start=30,
            char_end=33,
            sentence_text="Scaffold design is critical [1].",
            paragraph_text="Full paragraph about scaffolds and bone. "
            "Scaffold design is critical [1].",
            reference_id=1,
            reference_title="Scaffolds paper",
            mapping_confidence=1.0,
            mapping_method="number",
        )
        units = resolve_scopes([cit])
        assert len(units) == 1
        assert "Full paragraph" in units[0].paragraph_text


class TestCitationConverterParagraphText:
    """units_to_claims preserves paragraph_text."""

    def test_units_to_claims_paragraph_text(self) -> None:
        from refcheck.services.citation_converter import units_to_claims

        unit = VerificationUnit(
            manuscript_text="Sentence",
            paragraph_text="Full paragraph context here",
            scope_text="Sentence without marker",
            citation_marker="[5]",
            paragraph_index=0,
            reference_id=5,
            reference_title="Paper Five",
        )
        claims = units_to_claims([unit])
        assert len(claims) == 1
        assert claims[0].paragraph_text == "Full paragraph context here"


class TestCompoundSplitterParagraphText:
    """compound_splitter model_copy preserves and allows paragraph_text."""

    def test_split_numbered_preserves_paragraph_text(self) -> None:
        from refcheck.stages.detect_citations.compound_splitter import (
            split_compound_citation,
        )

        cit = CitationInstance(
            raw_marker="[1-3]",
            style="numbered_bracket",
            paragraph_index=0,
            char_start=20,
            char_end=25,
            paragraph_text="Pre-existing paragraph text",
        )
        results = split_compound_citation(cit)
        assert len(results) == 3
        for r in results:
            assert r.paragraph_text == "Pre-existing paragraph text"

    def test_split_author_year_preserves_paragraph_text(self) -> None:
        from refcheck.stages.detect_citations.compound_splitter import (
            split_compound_citation,
        )

        cit = CitationInstance(
            raw_marker="(Smith, 2020; Jones, 2021)",
            style="author_year_parenthetical",
            paragraph_index=0,
            char_start=10,
            char_end=35,
            paragraph_text="Context around the citation.",
        )
        results = split_compound_citation(cit)
        assert len(results) >= 2
        for r in results:
            assert r.paragraph_text == "Context around the citation."


class TestModelCopyContextAssignment:
    """Regression: context fields must be set via model_copy, not setattr.

    The bug: direct attribute assignment (cit.paragraph_text = text) can
    silently fail if the running process loads a stale .pyc that lacks
    the field. Using model_copy(update={...}) is Pydantic-safe and will
    raise a clear validation error if the field doesn't exist.
    """

    def test_model_copy_sets_paragraph_text(self) -> None:
        cit = CitationInstance(
            raw_marker="[1]",
            style="numbered_bracket",
            paragraph_index=0,
            char_start=10,
            char_end=13,
        )
        updated = cit.model_copy(update={"paragraph_text": "Full paragraph"})
        assert updated.paragraph_text == "Full paragraph"

    def test_model_copy_sets_sentence_context(self) -> None:
        cit = CitationInstance(
            raw_marker="[1]",
            style="numbered_bracket",
            paragraph_index=0,
            char_start=10,
            char_end=13,
        )
        updated = cit.model_copy(update={
            "sentence_text": "A sentence [1].",
            "sentence_start": 0,
            "sentence_end": 15,
            "paragraph_text": "A full paragraph. A sentence [1].",
        })
        assert updated.sentence_text == "A sentence [1]."
        assert updated.paragraph_text == "A full paragraph. A sentence [1]."
        assert updated.sentence_start == 0
        assert updated.sentence_end == 15

    def test_detect_all_citations_uses_model_copy(
        self,
    ) -> None:
        """Every citation from detect_all_citations must have paragraph_text.

        This is the exact regression test for the bug where paragraph_text
        was assigned via setattr and silently failed on stale bytecode.
        """
        from refcheck.stages.detect_citations import detect_all_citations

        manuscript = ParsedManuscript(
            filename="test.docx",
            sections=[
                ManuscriptSection(
                    heading="Introduction",
                    text=(
                        "Hydrogels are widely used in tissue engineering "
                        "(Smith et al., 2020). These materials show excellent "
                        "biocompatibility (Wang et al., 2021)."
                    ),
                ),
            ],
        )
        citations = detect_all_citations(manuscript)
        assert len(citations) > 0
        for cit in citations:
            assert cit.paragraph_text != "", (
                f"Citation '{cit.raw_marker}' has empty paragraph_text — "
                "model_copy context assignment may be broken"
            )
            assert cit.sentence_text != "", (
                f"Citation '{cit.raw_marker}' has empty sentence_text"
            )

    def test_detect_in_paragraph_uses_model_copy(self) -> None:
        """detect_in_paragraph must also set context via model_copy."""
        from refcheck.stages.detect_citations.detector import (
            detect_in_paragraph,
        )

        text = "Drug X is effective (Smith et al., 2020)."
        citations = detect_in_paragraph(text, para_idx=0, section="Intro")
        assert len(citations) > 0
        for cit in citations:
            assert cit.paragraph_text == text
            assert cit.sentence_text != ""


class TestEventClearing:
    """Pipeline clears stale events before re-running."""

    def test_clear_stale_events_function_exists(self) -> None:
        from refcheck.services.pipeline_runner import _clear_stale_events

        assert callable(_clear_stale_events)
