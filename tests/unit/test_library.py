"""Tests for reference library (V2 — SQLite persistence)."""

from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine

from refcheck.library.repository import (
    add_paper,
    compute_pdf_hash,
    find_paper,
    get_stats,
    search_papers,
)


@pytest.fixture()
def db() -> Session:
    """In-memory SQLite session for testing."""
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture()
def sample_pdf(tmp_path: Path) -> Path:
    """Create a minimal PDF file for testing."""
    pdf_file = tmp_path / "test_paper.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 test content here")
    return pdf_file


@pytest.fixture()
def pdf_dir(tmp_path: Path) -> Path:
    """Temporary directory for library PDFs."""
    lib_dir = tmp_path / "library"
    lib_dir.mkdir()
    return lib_dir


def test_add_paper_stores_and_returns(
    db: Session, sample_pdf: Path, pdf_dir: Path,
) -> None:
    """add_paper stores paper and returns it."""
    paper = add_paper(
        db, sample_pdf, doi="10.1234/test", pmid="12345",
        title="Test Paper", authors=["Smith J"], year=2024,
        journal="Nature", source="user_upload", pdf_dir=pdf_dir,
    )
    assert paper.id is not None
    assert paper.doi == "10.1234/test"
    assert paper.title == "Test Paper"
    assert paper.pdf_hash != ""


def test_add_paper_duplicate_hash_returns_existing(
    db: Session, sample_pdf: Path, pdf_dir: Path,
) -> None:
    """add_paper with same hash returns existing record."""
    paper1 = add_paper(
        db, sample_pdf, doi="10.1234/test", pmid=None,
        title="First", authors=[], year=None,
        journal=None, source="open_access", pdf_dir=pdf_dir,
    )
    paper2 = add_paper(
        db, sample_pdf, doi="10.5678/other", pmid=None,
        title="Second", authors=[], year=None,
        journal=None, source="user_upload", pdf_dir=pdf_dir,
    )
    assert paper1.id == paper2.id
    assert paper2.title == "First"  # kept original


def test_find_paper_by_doi(
    db: Session, sample_pdf: Path, pdf_dir: Path,
) -> None:
    """find_paper by DOI works."""
    add_paper(
        db, sample_pdf, doi="10.1234/test", pmid=None,
        title="DOI Paper", authors=[], year=None,
        journal=None, source="oa", pdf_dir=pdf_dir,
    )
    found = find_paper(db, doi="10.1234/test")
    assert found is not None
    assert found.title == "DOI Paper"


def test_find_paper_by_pmid(
    db: Session, sample_pdf: Path, pdf_dir: Path,
) -> None:
    """find_paper by PMID works."""
    add_paper(
        db, sample_pdf, doi=None, pmid="99999",
        title="PMID Paper", authors=[], year=None,
        journal=None, source="pubmed", pdf_dir=pdf_dir,
    )
    found = find_paper(db, pmid="99999")
    assert found is not None
    assert found.title == "PMID Paper"


def test_find_paper_by_fuzzy_title(
    db: Session, sample_pdf: Path, pdf_dir: Path,
) -> None:
    """find_paper by fuzzy title works (>92 match)."""
    add_paper(
        db, sample_pdf, doi=None, pmid=None,
        title="Hydrogel-based organ transplantation outcomes",
        authors=[], year=None, journal=None,
        source="oa", pdf_dir=pdf_dir,
    )
    found = find_paper(
        db, title="Hydrogel-based organ transplantation outcomes",
    )
    assert found is not None


def test_find_paper_returns_none_for_no_match(db: Session) -> None:
    """find_paper returns None when no match."""
    found = find_paper(db, doi="10.9999/nonexist")
    assert found is None


def test_search_papers_returns_ranked(
    db: Session, pdf_dir: Path, tmp_path: Path,
) -> None:
    """search_papers returns ranked results."""
    for i, title in enumerate(["Alpha paper", "Beta hydrogel", "Gamma study"]):
        pdf = tmp_path / f"paper_{i}.pdf"
        pdf.write_bytes(f"content-{i}".encode())
        add_paper(
            db, pdf, doi=None, pmid=None, title=title,
            authors=[], year=None, journal=None,
            source="oa", pdf_dir=pdf_dir,
        )
    results = search_papers(db, "hydrogel")
    assert len(results) >= 1
    assert results[0].title == "Beta hydrogel"


def test_get_stats_returns_counts(
    db: Session, sample_pdf: Path, pdf_dir: Path,
) -> None:
    """get_stats returns correct counts."""
    add_paper(
        db, sample_pdf, doi=None, pmid=None,
        title="Stats Paper", authors=[], year=None,
        journal=None, source="user_upload", pdf_dir=pdf_dir,
    )
    stats = get_stats(db)
    assert stats.total == 1
    assert stats.with_pdf == 1
    assert stats.by_source.get("user_upload") == 1


def test_compute_pdf_hash(sample_pdf: Path) -> None:
    """compute_pdf_hash returns consistent SHA-256."""
    h1 = compute_pdf_hash(sample_pdf)
    h2 = compute_pdf_hash(sample_pdf)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex length
