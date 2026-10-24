"""M6: identity check flags a wrong PDF that shares the title words and first author.

Synthetic stand-in for the real case (the 2020 edition of an annual report
attached to a reference for the 2017 edition, title text garbled by the font).
"""

from pathlib import Path

import fitz

from refcheck.models.reference import Reference
from refcheck.stages.resolve_gaps.identity_check import (
    apply_identity_checks,
    check_identity,
    read_first_pages_text,
)

_TITLE = "Injectable hydrogels for cartilage repair in osteoarthritic knees"
_BODY = (
    "Journal of Orthopaedic Research 2020; 38: 100-110. "
    "Background: cartilage lesions are common and heal poorly. " * 6
)


def _ref(**kw: object) -> Reference:
    base: dict[str, object] = {
        "id": 1, "title": _TITLE, "authors": ["J. Smith", "A. Jones"], "year": 2020,
    }
    base.update(kw)
    return Reference.model_validate(base)


_REPORT_2017 = "Registry 2017 Annual Data Report: Kidney"
_REPORT_BODY = "Transplant volumes rose again this year. " * 12


def _report_ref(**kw: object) -> Reference:
    base: dict[str, object] = {
        "id": 22, "title": _REPORT_2017, "authors": ["Morrow M", "Smith J"], "year": 2019,
        "doi": "10.5555/reg.15278",
    }
    base.update(kw)
    return Reference.model_validate(base)


def _make_report_pdf(path: Path, meta_title: str, first_page: str, second_page: str) -> Path:
    doc = fitz.open()
    for text in (first_page, second_page):
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(40, 40, 560, 800), text, fontsize=9)
    doc.set_metadata({"title": meta_title})
    doc.save(str(path))
    doc.close()
    return path


class TestHardSignals:
    def test_other_edition_is_mismatch_even_with_author_and_year(self) -> None:
        page = f"Registry 2020 Annual Data Report: Kidney\nM. Morrow, J. Smith\n{_REPORT_BODY}"
        result = check_identity(_report_ref(doi=None), page)
        assert result.author_found is True and result.year_found is True
        assert result.status == "mismatch"
        assert "2017" in result.reason and "2020" in result.reason

    def test_printed_doi_of_another_paper_is_mismatch(self) -> None:
        # Title only partly readable (garbled font), same first author: before M6
        # this was "inconclusive" (unverified) and the wrong paper was verified.
        page = ("Author manuscript. Please cite this article as doi: 10.5555/REG.16977\f"
                f"Rcgistry Annual Data bcport: Kidney\nM. Morrow\n{_REPORT_BODY} 2019")
        result = check_identity(_report_ref(title="Registry Annual Data Report: Kidney"), page)
        assert result.pdf_dois == ["10.5555/reg.16977"]
        assert result.author_found is True and result.title_coverage < 0.85
        assert result.status == "mismatch" and "10.5555/reg.16977" in result.reason

    def test_other_doi_but_full_title_author_and_year_match_is_inconclusive(self) -> None:
        page = ("doi: 10.5555/REG.16977\f"
                f"Registry Annual Data Report: Kidney\nM. Morrow\n{_REPORT_BODY} 2019")
        result = check_identity(_report_ref(title="Registry Annual Data Report: Kidney"), page)
        assert result.status == "unverified" and "check the reference DOI" in result.reason

    def test_wrong_reference_doi_with_matching_title_author_year_is_not_mismatch(self) -> None:
        # same title, author and year: most likely a typo in the reference DOI
        page = f"{_TITLE}\nJohn Smith, Anna Jones\ndoi: 10.5555/other.1\n{_BODY}"
        result = check_identity(_ref(doi="10.5555/typo.1"), page)
        assert result.status == "unverified" and "check the reference DOI" in result.reason

    def test_reference_doi_printed_supports_verification(self) -> None:
        page = f"Injectable hydrogels in knees\nJohn Smith\ndoi: 10.5555/ok.1\n{_BODY}"
        result = check_identity(_ref(doi="10.5555/OK.1"), page)
        assert result.status == "verified" and result.reason == "reference DOI printed"

    def test_dois_read_from_first_page_before_second(self) -> None:
        page = f"{_TITLE}\nJohn Smith\n{_BODY}\fReferences 10.5555/cited.9"
        assert check_identity(_ref(doi="10.5555/ok.1"), page).pdf_dois == ["10.5555/cited.9"]
        page = f"{_TITLE}\nJohn Smith doi 10.5555/ok.1\n{_BODY}\fReferences 10.5555/cited.9"
        assert check_identity(_ref(doi="10.5555/ok.1"), page).pdf_dois == ["10.5555/ok.1"]


class TestHardSignalsFromPdf:
    def test_metadata_title_and_printed_doi_flag_the_wrong_edition(self, tmp_path: Path) -> None:
        # Body title text garbled by the PDF font (as in the real case); only the
        # metadata title and the cover-page DOI reveal the 2020 edition.
        pdf = _make_report_pdf(
            tmp_path / "Morrow - 2019 - Registry 2017 Annual Data Report.pdf",
            meta_title="Registry 2020 Annual Data Report: Kidney",
            first_page="Author manuscript accepted for publication. Version of Record. "
                       "Please cite this article as doi: 10.5555/REG.16977",
            second_page=f"Rcgistry ab Annual Data bcport: Kidney\nM. Morrow\n{_REPORT_BODY}",
        )
        text = read_first_pages_text(pdf)
        assert text.startswith("Registry 2020 Annual Data Report") and "\f" in text
        out = apply_identity_checks([_report_ref(pdf_path=pdf)])
        assert out[0].identity_status == "mismatch"
