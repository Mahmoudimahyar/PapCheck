"""Hard identity signals: DOIs printed in a PDF and numbers inside titles (M6)."""

from refcheck.stages.resolve_gaps.identity_signals import (
    doi_conflict,
    dois_related,
    find_dois,
    title_number_conflict,
)


class TestFindDois:
    def test_normalized_unique_in_order(self) -> None:
        text = "DOI: 10.5555/SYNJ.16001. See https://doi.org/10.5555/synj.16001 and 10.5555/x."
        assert find_dois(text) == ["10.5555/synj.16001", "10.5555/x"]

    def test_parentheses_inside_doi_kept_unbalanced_dropped(self) -> None:
        assert find_dois("(doi 10.1016/S0140-6736(20)30183-5)") == [
            "10.1016/s0140-6736(20)30183-5"]
        assert find_dois("(see 10.1000/abc.12)") == ["10.1000/abc.12"]

    def test_no_doi(self) -> None:
        assert find_dois("Volume 10.5 of the report") == []


class TestDoisRelated:
    def test_same_and_extensions(self) -> None:
        assert dois_related("10.1/AB", "10.1/ab")
        assert dois_related("10.5555/978-3-000-00000-4_58", "10.5555/978-3-000-00000-4")
        assert dois_related("10.5555/synnano.4c00001", "10.5555/synnano.4c00001.s001")
        assert not dois_related("10.5555/synj.15002", "10.5555/synj.16001")
        assert not dois_related("10.1/ab", "10.1/abc")  # "abc" is not an extension of "ab"


class TestDoiConflict:
    def test_other_doi_and_reference_doi_absent(self) -> None:
        page = "Author manuscript. Please cite this article as doi: 10.5555/SYNJ.16001"
        assert doi_conflict("10.5555/synj.15002", find_dois(page), page) == "10.5555/synj.16001"

    def test_reference_doi_printed_too(self) -> None:
        page = "doi 10.9999/other and the article 10.5555/synj.15002"
        assert doi_conflict("10.5555/synj.15002", find_dois(page), page) is None

    def test_reference_doi_split_by_line_break(self) -> None:
        page = "Linked: 10.9999/other\nThis article: 10.5555/\nsynj.15002"
        assert doi_conflict("10.5555/synj.15002", find_dois(page), page) is None

    def test_preprint_version_is_not_a_conflict(self) -> None:
        page = "bioRxiv preprint doi: 10.1101/2020.01.01.123456"
        assert doi_conflict("10.1038/s41586-020-0001-1", find_dois(page), page) is None

    def test_nothing_to_compare(self) -> None:
        assert doi_conflict(None, ["10.1/x"], "10.1/x") is None
        assert doi_conflict("10.1/x", [], "") is None


class TestTitleNumberConflict:
    _TITLE = "Registry 2017 Annual Data Report: Heart"

    def test_edition_year_differs(self) -> None:
        page = "Registry 2020 Annual Data Report: Heart\nM. Morrow, J. Smith"
        assert title_number_conflict(self._TITLE, page) == ("2017", "2020")

    def test_right_number_present_wins(self) -> None:
        # the real 2017 report mentions last year's edition: not a conflict
        page = "Registry 2017 Annual Data Report: Heart. As in the Registry 2016 " \
               "Annual Data Report, listings rose."
        assert title_number_conflict(self._TITLE, page) is None

    def test_frame_split_over_lines(self) -> None:
        page = "Registry 2020\nAnnual Data\nReport: Heart"
        assert title_number_conflict(self._TITLE, page) == ("2017", "2020")

    def test_type_1_vs_type_2(self) -> None:
        title = "Islet transplantation in type 1 diabetes outcomes"
        page = "Islet transplantation in type 2 diabetes outcomes: a cohort"
        assert title_number_conflict(title, page) == ("1", "2")

    def test_citation_tail_parsed_as_title_never_conflicts(self) -> None:
        # M10-style garbled title: journal, volume, pages and DOI
        title = "Synth Nano 14, 301-309. doi: 10.5555/synnano.7b00001"
        assert title_number_conflict(title, "Synth Nano 2018, 14, 301-309") is None
        assert title_number_conflict("Hydrogels 5, 117", "Hydrogels 2021, 5, 117") is None

    def test_title_without_numbers(self) -> None:
        assert title_number_conflict("Hydrogels for cartilage", "Hydrogels 2020") is None
