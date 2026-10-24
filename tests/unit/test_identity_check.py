"""Reference identity check of attached PDFs (first-page text)."""

from pathlib import Path

import fitz

from refcheck.models.reference import Reference
from refcheck.stages.resolve_gaps.identity_check import (
    apply_identity_checks,
    check_identity,
    first_author_surname,
    read_first_pages_text,
)

_TITLE = "Injectable hydrogels for cartilage repair in osteoarthritic knees"
_BODY = (
    "Journal of Orthopaedic Research 2020; 38: 100-110. "
    "Background: cartilage lesions are common and heal poorly. " * 6
)


def _page(title: str, authors: str) -> str:
    return f"{title}\n{authors}\nReceived 12 March 2020\n{_BODY}"


def _ref(**kw: object) -> Reference:
    base: dict[str, object] = {
        "id": 1, "title": _TITLE, "authors": ["J. Smith", "A. Jones"], "year": 2020,
    }
    base.update(kw)
    return Reference.model_validate(base)


def _make_pdf(path: Path, text: str) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(40, 40, 560, 800), text, fontsize=9)
    doc.save(str(path))
    doc.close()
    return path


class TestCheckIdentity:
    def test_verified_when_title_and_author_present(self) -> None:
        result = check_identity(_ref(), _page(_TITLE, "John Smith, Anna Jones"))
        assert result.status == "verified"
        assert result.title_coverage == 1.0
        assert result.author_found is True

    def test_hyphenated_line_break(self) -> None:
        text = _page(
            "Injectable hydro-\ngels for cartilage repair in osteoarthritic knees",
            "J. Smith",
        )
        assert check_identity(_ref(), text).status == "verified"

    def test_pdf_ligatures(self) -> None:
        title = "Fibrin scaffolds modify fibroblast infiltration"
        text = _page(title.replace("fi", "ﬁ").replace("Fi", "ﬁ"), "J. Smith")
        assert "ﬁ" in text
        assert check_identity(_ref(title=title), text).status == "verified"

    def test_mismatch_when_title_and_author_absent(self) -> None:
        text = _page("Deep learning for retinal image segmentation", "Q. Wang, L. Chen")
        result = check_identity(_ref(), text)
        assert result.status == "mismatch"
        assert result.author_found is False

    def test_wrong_title_but_author_present_is_inconclusive(self) -> None:
        # e.g. a badly parsed reference title: never flag on one signal
        text = _page("A different title about tendon healing", "J. Smith")
        assert check_identity(_ref(), text).status == "unverified"

    def test_no_authors_needs_year_absent_too(self) -> None:
        text = "Deep learning for retinal segmentation. " * 10 + " Published 1999."
        assert check_identity(_ref(authors=[]), text).status == "mismatch"
        text_with_year = text + " Copyright 2021."
        assert check_identity(_ref(authors=[]), text_with_year).status == "unverified"

    def test_scanned_pdf_without_text_is_unverified(self) -> None:
        assert check_identity(_ref(), "  ").status == "unverified"

    def test_unusable_reference_title(self) -> None:
        result = check_identity(_ref(title="Front"), _page(_TITLE, "J. Smith"))
        assert result.status == "unverified"


class TestSurname:
    def test_formats(self) -> None:
        assert first_author_surname(["A. Lorne"]) == "lorne"
        assert first_author_surname(["Lorne A"]) == "lorne"
        assert first_author_surname(["Smith-Jones AB"]) == "smith jones"
        assert first_author_surname([]) == ""


class TestPdfIntegration:
    def test_read_and_apply(self, tmp_path: Path) -> None:
        good = _make_pdf(tmp_path / "good.pdf", _page(_TITLE, "John Smith"))
        bad = _make_pdf(
            tmp_path / "bad.pdf",
            _page("Deep learning for retinal image segmentation", "Q. Wang"),
        )
        assert "Injectable" in read_first_pages_text(good)
        refs = [
            _ref(id=1, pdf_path=good),
            _ref(id=2, pdf_path=bad),
            _ref(id=3),
            _ref(id=4, pdf_path=tmp_path / "missing.pdf"),
        ]
        out = apply_identity_checks(refs)
        assert [r.identity_status for r in out] == [
            "verified", "mismatch", "unverified", "unverified",
        ]

    def test_unreadable_file(self, tmp_path: Path) -> None:
        junk = tmp_path / "junk.pdf"
        junk.write_bytes(b"not a pdf at all")
        assert read_first_pages_text(junk) == ""
