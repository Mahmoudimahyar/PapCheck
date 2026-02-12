"""Unit tests for reference_extractor module."""

from refcheck.stages.parse_docx.reference_extractor import (
    extract_doi,
    extract_pmid,
    extract_year,
    is_reference_heading,
    parse_authors_title,
    parse_single_reference,
    split_reference_section,
)


class TestIsReferenceHeading:
    def test_references(self) -> None:
        assert is_reference_heading("References") is True

    def test_bibliography(self) -> None:
        assert is_reference_heading("Bibliography") is True

    def test_works_cited(self) -> None:
        assert is_reference_heading("Works Cited") is True

    def test_not_reference_heading(self) -> None:
        assert is_reference_heading("Introduction") is False

    def test_case_insensitive(self) -> None:
        assert is_reference_heading("REFERENCES") is True

    def test_reference_list(self) -> None:
        assert is_reference_heading("Reference List") is True


class TestExtractDOI:
    def test_doi_with_prefix(self) -> None:
        text = "Some paper. doi:10.1016/S0140-6736(20)30001-1"
        assert extract_doi(text) == "10.1016/S0140-6736(20)30001-1"

    def test_doi_url(self) -> None:
        text = "https://doi.org/10.1038/s41592-019-0001-1"
        assert extract_doi(text) == "10.1038/s41592-019-0001-1"

    def test_bare_doi(self) -> None:
        text = "Reference text 10.1234/test.2020"
        assert extract_doi(text) == "10.1234/test.2020"

    def test_no_doi(self) -> None:
        assert extract_doi("No DOI here") is None

    def test_doi_trailing_punctuation(self) -> None:
        text = "doi:10.1234/test."
        assert extract_doi(text) == "10.1234/test"


class TestExtractPMID:
    def test_pmid_with_prefix(self) -> None:
        assert extract_pmid("Some text PMID:32456789") == "32456789"

    def test_pubmed_prefix(self) -> None:
        assert extract_pmid("PubMed: 12345678") == "12345678"

    def test_no_pmid(self) -> None:
        assert extract_pmid("No PMID here") is None


class TestExtractYear:
    def test_year_in_reference(self) -> None:
        assert extract_year("Smith J. Cancer. 2020;1:1-5.") == 2020

    def test_no_year(self) -> None:
        assert extract_year("No year here") is None

    def test_multiple_years(self) -> None:
        assert extract_year("Published 2019, updated 2020") == 2019


class TestSplitReferenceSection:
    def test_bracket_format(self) -> None:
        """Handles [1] Author, Title, Journal format."""
        text = (
            "[1] A. Smith, Paper one, Journal, (2020).\n"
            "[2] B. Jones, Paper two, Journal, (2021).\n"
            "[3] C. Wilson, Paper three, Journal, (2022)."
        )
        refs = split_reference_section(text)
        assert len(refs) == 3

    def test_dot_format(self) -> None:
        """Handles 1. Author, Title format."""
        text = "1. First reference.\n2. Second reference.\n3. Third ref."
        refs = split_reference_section(text)
        assert len(refs) == 3

    def test_multiline_reference(self) -> None:
        text = (
            "[1] First reference line one\n"
            "continued on line two.\n"
            "[2] Second ref."
        )
        refs = split_reference_section(text)
        assert len(refs) == 2
        assert "continued" in refs[0]

    def test_paren_format(self) -> None:
        """Handles (1) Author format."""
        text = "(1) First reference.\n(2) Second reference."
        refs = split_reference_section(text)
        assert len(refs) == 2

    def test_fallback_line_per_ref(self) -> None:
        """Falls back to line-per-reference when no numbering detected."""
        text = (
            "Smith J et al. Paper A. Lancet. 2020.\n"
            "Jones K. Paper B. Nature. 2021.\n"
            "Wilson C. Paper C. Science. 2022."
        )
        refs = split_reference_section(text)
        assert len(refs) == 3


class TestParseAuthorsTitle:
    def test_vancouver_bracket_format(self) -> None:
        """[N] Initial. Surname, Initial. Surname, Title, Journal."""
        text = (
            "[2] A. Courties, I. Kouki, N. Soliman, "
            "Osteoarthritis year in review 2024, "
            "Osteoarthritis Cartilage, 32 (2024) 1397."
        )
        authors, title = parse_authors_title(text)
        assert len(authors) >= 2
        assert "Osteoarthritis year in review" in title

    def test_dot_format(self) -> None:
        """1. Author A, Author B. Title. Journal."""
        text = "1. Smith J, Doe A. Drug X study. Lancet. 2020."
        authors, title = parse_authors_title(text)
        assert len(authors) >= 1

    def test_no_authors_group_study(self) -> None:
        """Group study with no named authors."""
        text = (
            "[1] Global, regional, and national burden of osteoarthritis, "
            "Lancet Rheumatol, 5 (2023) e508."
        )
        # Should return the whole title even without authors
        _authors, title = parse_authors_title(text)
        assert "Global" in title or "burden" in title


class TestParseSingleReference:
    def test_full_reference(self) -> None:
        text = (
            "[1] A. Smith, B. Doe, Drug X reduces mortality, Lancet, "
            "(2020). doi:10.1016/test PMID:12345678"
        )
        ref = parse_single_reference(1, text)
        assert ref.id == 1
        assert ref.doi == "10.1016/test"
        assert ref.pmid == "12345678"
        assert ref.year == 2020

    def test_minimal_reference(self) -> None:
        text = "[5] Some paper title, Journal, (2019)."
        ref = parse_single_reference(5, text)
        assert ref.id == 5
        assert ref.year == 2019
        assert ref.title is not None
