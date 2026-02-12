"""Shared test fixtures for RefCheck tests."""

from pathlib import Path

import docx
import fitz
import pytest
from dotenv import load_dotenv

# Load .env file so API keys are available in tests
load_dotenv(Path(__file__).parent.parent / ".env")

FIXTURES_DIR = Path(__file__).parent / "fixtures"
MANUSCRIPTS_DIR = FIXTURES_DIR / "manuscripts"
PDFS_DIR = FIXTURES_DIR / "pdfs"


@pytest.fixture
def fixtures_dir() -> Path:
    """Path to the test fixtures directory."""
    return FIXTURES_DIR


@pytest.fixture
def manuscripts_dir() -> Path:
    """Path to the manuscript fixtures directory."""
    return MANUSCRIPTS_DIR


def create_test_docx(
    path: Path,
    ref_count: int = 10,
    include_dois: bool = True,
    include_pmids: bool = True,
    numbered_format: str = "bracket",
) -> Path:
    """Create a realistic test DOCX with numbered references.

    Args:
        path: Where to save the DOCX.
        ref_count: Number of references to generate.
        include_dois: Whether some refs have DOIs in the text.
        include_pmids: Whether some refs have PMIDs in the text.
        numbered_format: "bracket" for [1], "dot" for 1.
    """
    doc = docx.Document()
    doc.add_heading("Test Manuscript: Nanomedicine for Osteoarthritis", level=1)
    doc.add_heading("Abstract", level=2)
    doc.add_paragraph(
        "This study reviews recent advances in nanomedicine approaches "
        "for treating osteoarthritis [1, 2]."
    )
    doc.add_heading("1. Introduction", level=2)
    doc.add_paragraph(
        "Osteoarthritis is a chronic condition [1-3] affecting millions. "
        "Recent studies [4, 5] have shown that nanoparticles can deliver "
        "drugs directly to joints [6, 7]."
    )
    doc.add_heading("2. Methods", level=2)
    doc.add_paragraph(
        "We followed established protocols [8-10] for systematic review."
    )
    doc.add_heading("References", level=2)

    _SAMPLE_REFS = [
        (
            "A. Smith, B. Jones",
            "Drug X reduces inflammation in knee joints",
            "Lancet",
            2020,
            "10.1016/S0140-6736(20)30001-1",
            "32456789",
        ),
        (
            "C. Wilson, D. Lee",
            "CRISPR-based diagnostics for early disease detection",
            "Nature Methods",
            2019,
            "10.1038/s41592-019-0001-1",
            "31234567",
        ),
        (
            "E. Brown, F. Garcia",
            "Nanoparticle delivery systems for targeted therapy",
            "Advanced Drug Delivery Reviews",
            2021,
            "10.1016/j.addr.2021.01.001",
            None,
        ),
        (
            "G. Martinez",
            "Global burden of osteoarthritis in aging populations",
            "Lancet Rheumatol",
            2023,
            None,
            None,
        ),
        (
            "H. Taylor, I. Anderson",
            "Mesenchymal stem cell therapy for cartilage repair",
            "Arthritis Res Ther",
            2018,
            "10.1186/s13075-018-0001-1",
            None,
        ),
        (
            "J. Thomas",
            "Exosome-based therapeutics for joint diseases",
            "Biomaterials",
            2022,
            None,
            "35678901",
        ),
        (
            "K. White, L. Harris",
            "siRNA delivery to chondrocytes via lipid nanoparticles",
            "Mol Ther Nucleic Acids",
            2021,
            "10.1016/j.omtn.2021.05.001",
            None,
        ),
        (
            "M. Clark",
            "Autophagy pathways in age-related joint degeneration",
            "Cell Death Dis",
            2020,
            None,
            None,
        ),
        (
            "N. Lewis, O. Walker",
            "Anti-inflammatory effects of curcumin nanoformulations",
            "Int J Pharm",
            2019,
            "10.1016/j.ijpharm.2019.118001",
            "30987654",
        ),
        (
            "P. Hall, Q. Young",
            "Machine learning approaches for drug delivery optimization",
            "Adv Sci",
            2024,
            None,
            None,
        ),
    ]

    for i in range(min(ref_count, len(_SAMPLE_REFS))):
        authors, title, journal, year, doi, pmid = _SAMPLE_REFS[i]
        ref_text = f"[{i + 1}] {authors}, {title}, {journal}, ({year})"
        if doi and include_dois:
            ref_text += f". doi:{doi}"
        if pmid and include_pmids:
            ref_text += f" PMID:{pmid}"
        ref_text += "."
        doc.add_paragraph(ref_text)

    # Add extra generic references if more than 10 needed
    for i in range(len(_SAMPLE_REFS), ref_count):
        doc.add_paragraph(
            f"[{i + 1}] R. Author{i}, S. Coauthor{i}, "
            f"Study number {i} on nanoparticle therapy, "
            f"J Generic, ({2015 + i % 10})."
        )

    doc.save(str(path))
    return path


def create_test_pdf(
    path: Path,
    title: str,
    doi: str = "",
    abstract: str = "",
) -> Path:
    """Create a test PDF with title in large font and optional DOI."""
    doc = fitz.open()
    page = doc.new_page()

    # Title in large font (simulates real paper)
    page.insert_text((72, 72), title, fontsize=18)

    if abstract:
        page.insert_text((72, 120), f"Abstract: {abstract}", fontsize=10)
    else:
        page.insert_text(
            (72, 120),
            "Abstract: This paper presents novel findings.",
            fontsize=10,
        )

    if doi:
        page.insert_text((72, 160), f"https://doi.org/{doi}", fontsize=9)

    doc.save(str(path))
    doc.close()
    return path
