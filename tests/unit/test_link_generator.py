"""Tests for reference link generation (V2)."""

from refcheck.stages.resolve_gaps.link_generator import generate_reference_links


def test_all_identifiers_present() -> None:
    """All links generated when DOI, PMID, and title available."""
    links = generate_reference_links(
        doi="10.1016/j.actbio.2024.01.001",
        pmid="12345678",
        title="Hydrogel-based organ transplantation",
    )
    assert links["doi_url"] == "https://doi.org/10.1016/j.actbio.2024.01.001"
    assert links["pubmed_url"] == "https://pubmed.ncbi.nlm.nih.gov/12345678/"
    assert links["scholar_url"] is not None
    assert "Hydrogel" in links["scholar_url"]


def test_doi_only() -> None:
    """Only DOI link when only DOI available."""
    links = generate_reference_links(doi="10.1234/test", pmid=None, title=None)
    assert links["doi_url"] == "https://doi.org/10.1234/test"
    assert links["pubmed_url"] is None
    assert links["scholar_url"] is None


def test_no_identifiers() -> None:
    """All links None when no identifiers."""
    links = generate_reference_links(doi=None, pmid=None, title=None)
    assert links["doi_url"] is None
    assert links["pubmed_url"] is None
    assert links["scholar_url"] is None
    assert links["pmc_url"] is None


def test_title_url_encoding() -> None:
    """Title with spaces and special chars is URL-encoded."""
    links = generate_reference_links(
        doi=None, pmid=None, title="Effect of Drug X & Y on Z",
    )
    assert links["scholar_url"] is not None
    assert "Effect" in links["scholar_url"]
    assert "%26" in links["scholar_url"]  # & encoded


def test_long_title_truncated() -> None:
    """Title over 200 chars is truncated for URL."""
    long_title = "A" * 300
    links = generate_reference_links(doi=None, pmid=None, title=long_title)
    assert links["scholar_url"] is not None
    # URL should use truncated version (200 chars)
    assert len(links["scholar_url"]) < 300


def test_pmc_id_generates_pmc_url() -> None:
    """PMC ID produces a PMC URL."""
    links = generate_reference_links(
        doi=None, pmid=None, title=None, pmc_id="PMC12345",
    )
    assert links["pmc_url"] == "https://pmc.ncbi.nlm.nih.gov/articles/PMC12345/"


def test_pmc_id_without_prefix() -> None:
    """PMC ID without 'PMC' prefix gets it added."""
    links = generate_reference_links(
        doi=None, pmid=None, title=None, pmc_id="12345",
    )
    assert links["pmc_url"] == "https://pmc.ncbi.nlm.nih.gov/articles/PMC12345/"


def test_journal_url_passed_through() -> None:
    """journal_url is included in results when provided."""
    links = generate_reference_links(
        doi=None, pmid=None, title=None,
        journal_url="https://example.com/article/123",
    )
    assert links["journal_url"] == "https://example.com/article/123"


def test_all_links_with_pmc_and_journal() -> None:
    """All 5 link types populated when everything available."""
    links = generate_reference_links(
        doi="10.1234/test",
        pmid="99999",
        title="Test Paper",
        pmc_id="PMC55555",
        journal_url="https://journal.example.com/article",
    )
    assert links["doi_url"] is not None
    assert links["pubmed_url"] is not None
    assert links["scholar_url"] is not None
    assert links["pmc_url"] is not None
    assert links["journal_url"] is not None
