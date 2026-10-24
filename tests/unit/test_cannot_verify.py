"""Tests for cannot-verify classification and reference type detection (V2)."""

from refcheck.models.cannot_verify import (
    CannotVerifyReason,
    classify_cannot_verify,
)
from refcheck.stages.parse_docx.reference_classifier import (
    classify_reference_type,
)


class TestClassifyCannotVerify:
    """Tests for classify_cannot_verify."""

    def test_no_source_with_doi_is_paywalled(self) -> None:
        result = classify_cannot_verify(
            reference_source_status="not_found",
            reference_doi="10.1234/test",
            reference_type="journal_article",
            text_quality_score=1.0,
            section_relevance="high",
            source_coverage="no_source",
            had_llm_error=False,
        )
        assert result == CannotVerifyReason.NO_PDF_PAYWALLED

    def test_no_source_without_doi_is_not_found(self) -> None:
        result = classify_cannot_verify(
            reference_source_status="not_found",
            reference_doi=None,
            reference_type="journal_article",
            text_quality_score=1.0,
            section_relevance="high",
            source_coverage="no_source",
            had_llm_error=False,
        )
        assert result == CannotVerifyReason.NO_PDF_NOT_FOUND

    def test_no_source_website(self) -> None:
        result = classify_cannot_verify(
            reference_source_status="not_found",
            reference_doi=None,
            reference_type="website",
            text_quality_score=1.0,
            section_relevance="high",
            source_coverage="no_source",
            had_llm_error=False,
        )
        assert result == CannotVerifyReason.NO_PDF_WEBSITE

    def test_no_source_book_chapter(self) -> None:
        result = classify_cannot_verify(
            reference_source_status="not_found",
            reference_doi=None,
            reference_type="book_chapter",
            text_quality_score=1.0,
            section_relevance="high",
            source_coverage="no_source",
            had_llm_error=False,
        )
        assert result == CannotVerifyReason.NO_PDF_BOOK_CHAPTER

    def test_llm_error(self) -> None:
        result = classify_cannot_verify(
            reference_source_status="found",
            reference_doi="10.1234/test",
            reference_type="journal_article",
            text_quality_score=0.8,
            section_relevance="high",
            source_coverage="full_text",
            had_llm_error=True,
        )
        assert result == CannotVerifyReason.LLM_ERROR

    def test_low_quality_metadata_only(self) -> None:
        result = classify_cannot_verify(
            reference_source_status="found",
            reference_doi="10.1234/test",
            reference_type="journal_article",
            text_quality_score=0.1,
            section_relevance="high",
            source_coverage="full_text",
            had_llm_error=False,
        )
        assert result == CannotVerifyReason.PDF_METADATA_ONLY

    def test_low_quality_supplement(self) -> None:
        result = classify_cannot_verify(
            reference_source_status="found",
            reference_doi="10.1234/test",
            reference_type="journal_article",
            text_quality_score=0.2,
            section_relevance="high",
            source_coverage="full_text",
            had_llm_error=False,
        )
        assert result == CannotVerifyReason.PDF_SUPPLEMENT

    def test_irrelevant_section(self) -> None:
        result = classify_cannot_verify(
            reference_source_status="found",
            reference_doi="10.1234/test",
            reference_type="journal_article",
            text_quality_score=0.8,
            section_relevance="low",
            source_coverage="full_text",
            had_llm_error=False,
        )
        assert result == CannotVerifyReason.SECTION_IRRELEVANT

    def test_abstract_insufficient(self) -> None:
        result = classify_cannot_verify(
            reference_source_status="found",
            reference_doi="10.1234/test",
            reference_type="journal_article",
            text_quality_score=0.8,
            section_relevance="high",
            source_coverage="abstract_only",
            had_llm_error=False,
        )
        assert result == CannotVerifyReason.ABSTRACT_INSUFFICIENT


class TestClassifyReferenceType:
    """Tests for classify_reference_type."""

    def test_journal_article_default(self) -> None:
        result = classify_reference_type(
            "Smith, J. (2020). Title. Nature, 580, 123-130.",
            doi="10.1038/test",
        )
        assert result == "journal_article"

    def test_book_chapter(self) -> None:
        result = classify_reference_type(
            "Smith J. Chapter 5. In: Jones A (eds.). Book Title. "
            "Springer Press, pp. 100-120.",
        )
        assert result == "book_chapter"

    def test_website_no_doi(self) -> None:
        result = classify_reference_type(
            "OPTN/HRSA. https://optn.transplant.hrsa.gov/data/",
        )
        assert result == "website"

    def test_url_with_doi_is_not_website(self) -> None:
        result = classify_reference_type(
            "Smith J. Title. https://doi.org/10.1234/test",
            doi="10.1234/test",
        )
        assert result != "website"

    def test_preprint(self) -> None:
        result = classify_reference_type(
            "Smith J. (2024). bioRxiv preprint.",
        )
        assert result == "preprint"

    def test_conference_paper(self) -> None:
        result = classify_reference_type(
            "Smith J. Proceedings of the IEEE Conference on...",
        )
        assert result == "conference_paper"
