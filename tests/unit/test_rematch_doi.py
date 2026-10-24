"""Re-match DOIs: a truncated reference DOI or a longer printed DOI is not the same work.

Regression (review of the re-match pass, synthetic DOIs only): a reference DOI cut
to a journal stem matched every longer DOI of that journal printed in a PDF, and
the prefix counted as the same DOI, so a wrong PDF could be linked on the DOI route.
"""

from pathlib import Path

import pytest

from refcheck.stages.match_pdfs.doi_placement import (
    complete_doi,
    doi_pattern,
    related_dois,
    rematch_doi,
)
from refcheck.stages.match_pdfs.pdf_profile import PdfProfile, build_profile
from refcheck.stages.match_pdfs.rematch_evidence import assess, decide
from tests.unit.rematch_fakes import DOI_A, PROSE, TITLE_A, ref

_HEAD = f"{TITLE_A}\nJane Doe, Kim Roe\nPublished 2021\n"
_SHORT = "10.5555/synth.01234"  # complete, but a prefix of DOI_A


def _profile(page1: str) -> PdfProfile:
    return build_profile(Path("x.pdf"), [page1, PROSE])


@pytest.mark.parametrize("doi", ["10.5555/synth", "10.5555/j.synth", "10.5555/ab12",
                                 "10.5555/synth-", "10.5555/", "synth.01234", ""])
def test_truncated_reference_dois_are_not_searched(doi: str) -> None:
    assert not complete_doi(doi) and rematch_doi(doi) == "" and doi_pattern(doi) is None


@pytest.mark.parametrize("doi", [DOI_A, _SHORT, "10.5555/S0000-0000(21)00001-X",
                                 "https://doi.org/10.5555/j.1600-0000.2011.00001.x"])
def test_complete_reference_dois_are_searched(doi: str) -> None:
    assert complete_doi(doi) and doi_pattern(doi) is not None


@pytest.mark.parametrize("printed", [f"{_SHORT}-56", f"{_SHORT}.2", f"{_SHORT}/x7",
                                     "10.5555/SYNTH.01234\n.2009"])
def test_a_longer_printed_doi_is_another_work(printed: str) -> None:
    pattern = doi_pattern(_SHORT)
    assert pattern is not None and not pattern.search(f"doi: {printed} Received")


@pytest.mark.parametrize("printed", [f"{DOI_A}.g001", f"{DOI_A}.s001", f"{DOI_A}.t002",
                                     f"{DOI_A}/suppl_file/si.pdf", f"{DOI_A}.\nReceived"])
def test_si_extensions_and_sentence_ends_still_match(printed: str) -> None:
    pattern = doi_pattern(DOI_A)
    assert pattern is not None and pattern.search(f"doi: {printed} x")


def test_related_dois_accepts_only_si_extensions_and_cut_prints() -> None:
    assert related_dois(DOI_A, DOI_A) and related_dois(DOI_A, f"{DOI_A}.g001")
    assert related_dois(DOI_A, f"{DOI_A}/suppl_file/x.pdf")
    assert related_dois(DOI_A, "10.5555/synth")  # printed DOI cut at a line break
    assert related_dois(DOI_A, "10.5555/synth.01234-")
    assert not related_dois(_SHORT, DOI_A) and not related_dois(_SHORT, f"{_SHORT}.2")
    assert not related_dois(DOI_A, _SHORT)  # a complete DOI is another work
    assert not related_dois(DOI_A, "10.5555/syn") and not related_dois("", DOI_A)


def test_truncated_reference_doi_neither_links_nor_conflicts() -> None:
    stem = ref(1, doi="10.5555/synth")
    ev = assess(stem, _profile(f"{_HEAD}https://doi.org/10.5555/synth.2009.0001\n{PROSE}"))
    assert ev.doi_page == 0 and not ev.doi_primary and not ev.doi_conflict
    assert decide(stem, ev) == "rematch_title"  # the title route still applies


def test_longer_own_doi_blocks_a_shorter_reference_doi() -> None:
    short = ref(1, doi=_SHORT)
    ev = assess(short, _profile(f"{_HEAD}https://doi.org/{DOI_A}\n{PROSE}"))
    assert ev.doi_page == 0 and not ev.doi_primary and ev.doi_conflict
    assert decide(short, ev) is None


def test_figure_doi_after_the_own_doi_is_no_conflict() -> None:
    page = f"{_HEAD}https://doi.org/{DOI_A}\nFigure 1 doi:{DOI_A}.g001\n{PROSE}"
    ev = assess(ref(1), _profile(page))
    assert ev.doi_primary and not ev.doi_conflict and decide(ref(1), ev) == "rematch_doi"
