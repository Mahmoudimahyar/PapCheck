"""M10 (resolver side): a garbled parsed title is replaced by the DOI/PMID record's title."""

import pytest

from refcheck.models.reference import Reference
from refcheck.stages.resolve_gaps.doi_records import CrossrefRecord
from refcheck.stages.resolve_gaps.enrichment import apply_records
from refcheck.stages.resolve_gaps.pubmed_batch import PubMedRecord
from refcheck.stages.resolve_gaps.title_repair import (
    clean_api_title,
    title_looks_bad,
    title_repair_update,
)

_TITLE = "Shape-memory hydrogels for minimally invasive cartilage repair in rabbits"
_RAW = (f"Doe, J., and Roe, K. (2018). {_TITLE}. J. Synth. Biomater. 14, 301-309. "
        "doi: 10.5555/jsb.7b00001")


def _ref(title: str, raw: str = _RAW, **kw: object) -> Reference:
    base: dict[str, object] = {"id": 65, "title": title, "raw_text": raw,
                               "doi": "10.5555/jsb.7b00001"}
    base.update(kw)
    return Reference.model_validate(base)


class TestTitleLooksBad:
    @pytest.mark.parametrize("title", [
        "J. Synth. Biomater. 14, 301-309. doi: 10.5555/jsb.7b00001",  # journal/vol/pages/doi
        "Synth Gels 5, 117. doi: 10.5555/gels5020117",
        "Synth Inj., 210-219. doi: 10.5555/978-3-000",
        "Synth Biomater 9, 140-148",  # no DOI, still a citation tail
        "Front",  # too short
        "",
    ])
    def test_garbled(self, title: str) -> None:
        assert title_looks_bad(title)

    @pytest.mark.parametrize("title", [
        _TITLE,
        "Registry 2017 Annual Data Report: Heart",
        "Effects of IL-2, 6 and 10 on regulatory T cells in transplanted islets",
    ])
    def test_real_titles(self, title: str) -> None:
        assert not title_looks_bad(title)


class TestCleanApiTitle:
    def test_markup_trailing_period_and_brackets(self) -> None:
        assert clean_api_title("Hydrogel <i>scaffolds</i> for cartilage.") == \
            "Hydrogel scaffolds for cartilage"
        assert clean_api_title("[Translated title of a paper].") == "Translated title of a paper"
        assert clean_api_title("[18F]FDG uptake in grafts.") == "[18F]FDG uptake in grafts"


class TestTitleRepairUpdate:
    def test_garbled_title_replaced_from_crossref(self) -> None:
        ref = _ref("J. Synth. Biomater. 14, 301-309. doi: 10.5555/jsb.7b00001")
        update = title_repair_update(ref, crossref_title=_TITLE)
        assert update == {"title": _TITLE, "repair_applied": "title_from_api"}

    def test_pubmed_title_used_when_no_crossref(self) -> None:
        ref = _ref("Synth Biomater 9, 140-148")
        update = title_repair_update(ref, pubmed_title=f"{_TITLE}.",
                                     pubmed_doi="10.5555/JSB.7b00001")
        assert update["title"] == _TITLE

    def test_pubmed_record_of_another_doi_ignored(self) -> None:
        ref = _ref("Synth Biomater 9, 140-148")
        assert title_repair_update(ref, pubmed_title=_TITLE, pubmed_doi="10.5555/other") == {}

    def test_good_title_kept(self) -> None:
        assert title_repair_update(_ref(_TITLE), crossref_title=_TITLE.upper()) == {}
        assert title_repair_update(_ref(_TITLE), crossref_title=_TITLE + ".") == {}

    def test_dissimilar_title_replaced_when_reference_text_contains_record_title(self) -> None:
        ref = _ref("Shape-memory hydrogels")  # truncated parse
        assert title_repair_update(ref, crossref_title=_TITLE)["title"] == _TITLE

    def test_record_title_absent_from_reference_text_is_not_trusted(self) -> None:
        # a wrong DOI in the manuscript points at another paper: keep the parsed title
        ref = _ref(_TITLE)
        assert title_repair_update(ref, crossref_title="Deep learning for retinal images") == {}

    def test_bad_title_without_reference_text_replaced(self) -> None:
        ref = _ref("Synth Gels 5, 117. doi: 10.5555/gels5020117", raw="")
        assert title_repair_update(ref, crossref_title=_TITLE)["title"] == _TITLE

    def test_no_record_title(self) -> None:
        assert title_repair_update(_ref("Gels 5, 117. doi: 10.5555/x"), crossref_title="") == {}


class TestApplyRecords:
    def test_crossref_record_repairs_title_and_keeps_raw_text(self) -> None:
        ref = _ref("J. Synth. Biomater. 14, 301-309. doi: 10.5555/jsb.7b00001")
        out = apply_records(ref, None, CrossrefRecord(doi=ref.doi or "", title=_TITLE), "")
        assert out.title == _TITLE and out.repair_applied == "title_from_api"
        assert out.raw_text == _RAW

    def test_pubmed_record_repairs_title(self) -> None:
        ref = _ref("Synth Biomater 9, 140-148", pmid="111")
        pm = PubMedRecord(pmid="111", title=f"{_TITLE}.", doi="10.5555/jsb.7b00001")
        assert apply_records(ref, pm, None, "").title == _TITLE

    def test_no_records_no_change(self) -> None:
        ref = _ref("Synth Biomater 9, 140-148")
        assert apply_records(ref, None, None, "") is ref
