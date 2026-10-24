"""Shared library service (V5.8, G3): references without a usable PDF get one from the
local library before the abstract fallback; populate never stores a wrong PDF.
Synthetic PDFs, real identity check, library isolated in tmp_path."""

import shutil
from pathlib import Path

import pytest

from refcheck.library.store import pdf_key
from refcheck.services.library import (
    enrich_from_library,
    enrich_from_library_async,
    populate_library,
)
from tests.unit.rematch_fakes import DOI_B, TITLE_B, article, ref, supplement


@pytest.fixture(autouse=True)
def library(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """An empty local library; the OA fetch off (its default)."""
    lib = tmp_path / "library"
    monkeypatch.setenv("REFCHECK_SHARED_LIBRARY_DIR", str(lib))
    monkeypatch.setenv("REFCHECK_LIBRARY_DB", str(tmp_path / "library.db"))
    monkeypatch.delenv("REFCHECK_OA_FETCH", raising=False)
    return lib


def _store(lib: Path, name: str, **kw: str) -> Path:
    lib.mkdir(parents=True, exist_ok=True)
    return article(lib / name, **kw)  # type: ignore[arg-type]


def _wrong(path: Path) -> Path:
    return article(path, title=TITLE_B, doi_line=f"doi: {DOI_B}", authors="Ann Poe, Lu Moe")


class TestEnrichFromLibrary:
    def test_reference_without_pdf_gets_its_keyed_library_copy(self, library: Path) -> None:
        stored = _store(library, f"{pdf_key(ref(1))}.pdf")
        out = enrich_from_library([ref(1, source_status="pending")])
        assert out[0].pdf_path == stored and out[0].replaced_upload_reason is None
        assert (out[0].pdf_source, out[0].source_status) == ("library", "found")

    def test_wrong_upload_is_replaced_by_a_library_pdf_found_by_title(
            self, library: Path, tmp_path: Path) -> None:
        upload = _wrong(tmp_path / "upload.pdf")
        stored = _store(library, "title_scan.pdf", doi_line="")
        out = enrich_from_library([ref(34, pdf_path=upload, pdf_source="user_upload")])
        assert out[0].pdf_path == stored and out[0].pdf_source == "library"
        assert out[0].identity_status == "unverified"  # re-checked at the end of stage 4
        assert out[0].replaced_upload_reason == "identity_mismatch"  # still reported
        assert upload.exists()  # the user's file is never touched

    def test_wrong_paper_stored_under_the_key_is_not_used(self, library: Path) -> None:
        library.mkdir()
        _wrong(library / f"{pdf_key(ref(2))}.pdf")
        out = enrich_from_library([ref(2)])
        assert out[0].pdf_path is None and out[0].pdf_source is None

    def test_supplement_upload_and_library_supplement_stay_unlinked(
            self, library: Path, tmp_path: Path) -> None:
        upload = supplement(tmp_path / "nn_si_001.pdf")
        library.mkdir()
        shutil.copy2(upload, library / f"{pdf_key(ref(3))}.pdf")
        out = enrich_from_library([ref(3, pdf_path=upload, pdf_source="user_upload")])
        assert out[0].pdf_path == upload and out[0].pdf_source == "user_upload"

    def test_usable_pdf_is_kept(self, library: Path, tmp_path: Path) -> None:
        upload = article(tmp_path / "good.pdf")
        _store(library, "other_copy.pdf")
        out = enrich_from_library([ref(4, pdf_path=upload, pdf_source="user_upload")])
        assert out[0].pdf_path == upload and out[0].pdf_source == "user_upload"

    def test_missing_library_changes_nothing_and_creates_nothing(self, library: Path) -> None:
        out = enrich_from_library([ref(5)])
        assert out[0].pdf_path is None and not library.exists()

    async def test_async_variant(self, library: Path) -> None:
        stored = _store(library, f"{pdf_key(ref(6))}.pdf")
        out = await enrich_from_library_async([ref(6)])
        assert out[0].pdf_path == stored


class TestPopulateLibrary:
    def test_usable_pdf_is_added(self, library: Path, tmp_path: Path) -> None:
        pdf = article(tmp_path / "resolved.pdf")
        assert populate_library([ref(1, pdf_path=pdf, identity_status="verified")]) == 1
        assert (library / f"{pdf_key(ref(1))}.pdf").exists()

    def test_supplement_mismatch_and_unreadable_are_skipped(
            self, library: Path, tmp_path: Path) -> None:
        si = supplement(tmp_path / "x_si_001.pdf")
        wrong = _wrong(tmp_path / "wrong.pdf")
        broken = tmp_path / "broken.pdf"
        broken.write_bytes(b"%PDF-1.4 not really")
        refs = [ref(1, pdf_path=si), ref(2, pdf_path=wrong, identity_status="mismatch"),
                ref(3, pdf_path=broken)]
        assert populate_library(refs) == 0
        assert not library.exists() or not list(library.glob("*.pdf"))

    def test_existing_entry_is_kept(self, library: Path, tmp_path: Path) -> None:
        stored = _store(library, f"{pdf_key(ref(1))}.pdf")
        before = stored.read_bytes()
        pdf = article(tmp_path / "again.pdf", body="Another copy of the article text. " * 40)
        assert populate_library([ref(1, pdf_path=pdf, identity_status="verified")]) == 0
        assert stored.read_bytes() == before

    def test_poisoned_entry_is_replaced_by_a_verified_pdf(
            self, library: Path, tmp_path: Path) -> None:
        library.mkdir()
        poisoned = _wrong(library / f"{pdf_key(ref(1))}.pdf")
        right = article(tmp_path / "right.pdf")
        assert populate_library([ref(1, pdf_path=right, identity_status="unverified")]) == 0
        assert populate_library([ref(1, pdf_path=right, identity_status="verified")]) == 1
        assert poisoned.read_bytes() == right.read_bytes()

    def test_library_copy_is_not_added_again(self, library: Path) -> None:
        stored = _store(library, "title_scan.pdf")
        assert populate_library([ref(1, pdf_path=stored, pdf_source="library",
                                     identity_status="verified")]) == 0
        assert sorted(p.name for p in library.glob("*.pdf")) == ["title_scan.pdf"]

    def test_reference_without_doi_or_title_is_not_stored(
            self, library: Path, tmp_path: Path) -> None:
        pdf = article(tmp_path / "anon.pdf")
        assert populate_library([ref(9, doi=None, title="", pdf_path=pdf)]) == 0
