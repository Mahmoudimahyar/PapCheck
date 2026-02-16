"""Tests for citation-to-reference mapping."""

from refcheck.models.citation import CitationInstance
from refcheck.models.reference import Reference
from refcheck.stages.detect_citations.reference_mapper import (
    map_citations_to_references,
)


def _make_ref(
    ref_id: int, authors: list[str], year: int | None = None,
    title: str = "Test Paper",
) -> Reference:
    return Reference(id=ref_id, authors=authors, year=year, title=title)


def _make_cit(
    authors: list[str] | None = None, year: str | None = None,
    number: int | None = None,
) -> CitationInstance:
    return CitationInstance(
        raw_marker="test",
        style="author_year_parenthetical",
        paragraph_index=0,
        char_start=0,
        char_end=10,
        authors=authors or [],
        year=year,
        number=number,
    )


class TestReferenceMapper:
    def test_exact_author_year(self) -> None:
        refs = [_make_ref(1, ["Smith, John"], 2020)]
        cits = [_make_cit(authors=["Smith"], year="2020")]
        map_citations_to_references(cits, refs)
        assert cits[0].reference_id == 1
        assert cits[0].mapping_confidence == 0.95
        assert cits[0].mapping_method == "exact_author_year"

    def test_fuzzy_author_accent(self) -> None:
        refs = [_make_ref(1, ["García, Maria"], 2020)]
        cits = [_make_cit(authors=["Garcia"], year="2020")]
        map_citations_to_references(cits, refs)
        assert cits[0].reference_id == 1
        # Accent normalization makes this an exact match
        assert cits[0].mapping_confidence >= 0.85

    def test_numbered_lookup(self) -> None:
        refs = [_make_ref(7, ["Someone"], 2020)]
        cits = [_make_cit(number=7)]
        cits[0].style = "numbered_bracket"
        map_citations_to_references(cits, refs)
        assert cits[0].reference_id == 7
        assert cits[0].mapping_confidence == 1.0
        assert cits[0].mapping_method == "number"

    def test_two_author_match(self) -> None:
        refs = [_make_ref(1, ["Smith, J", "Jones, K"], 2020)]
        cits = [_make_cit(authors=["Smith", "Jones"], year="2020")]
        map_citations_to_references(cits, refs)
        assert cits[0].reference_id == 1

    def test_author_only_no_date(self) -> None:
        refs = [_make_ref(1, ["Desai, A"], 2019)]
        cits = [_make_cit(authors=["Desai"], year=None)]
        map_citations_to_references(cits, refs)
        assert cits[0].reference_id == 1
        assert cits[0].mapping_confidence == 0.70

    def test_unresolved(self) -> None:
        refs = [_make_ref(1, ["Smith"], 2020)]
        cits = [_make_cit(authors=["Unknown"], year="2025")]
        map_citations_to_references(cits, refs)
        assert cits[0].mapping_method == "unresolved"
        assert cits[0].reference_id is None

    def test_particle_author(self) -> None:
        refs = [_make_ref(1, ["de Vries, H"], 2020)]
        cits = [_make_cit(authors=["de Vries"], year="2020")]
        map_citations_to_references(cits, refs)
        assert cits[0].reference_id == 1
