"""Opt-in OA fetch through the library service (V5.8, G3): a download is identity-checked
like an upload and stored in the library; a wrong paper is discarded. Mocked HTTP only."""

from pathlib import Path

import httpx
import pytest

from refcheck.library.store import pdf_key
from refcheck.services.library import enrich_from_library
from tests.unit.rematch_fakes import DOI_B, TITLE_B, article, ref


@pytest.fixture(autouse=True)
def library(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    lib = tmp_path / "library"
    monkeypatch.setenv("REFCHECK_SHARED_LIBRARY_DIR", str(lib))
    monkeypatch.setenv("REFCHECK_LIBRARY_DB", str(tmp_path / "library.db"))
    monkeypatch.setenv("REFCHECK_CONTACT_EMAIL", "tester@example.org")
    monkeypatch.setenv("REFCHECK_OA_FETCH", "on")
    return lib


def _client(pdf: bytes, seen: list[str]) -> httpx.Client:
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        if request.url.host == "api.unpaywall.org":
            return httpx.Response(200, json={
                "best_oa_location": {"url_for_pdf": "https://repo.example.org/a.pdf"}})
        if request.url.host == "repo.example.org":
            return httpx.Response(200, headers={"content-type": "application/pdf"}, content=pdf)
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handle))


def test_open_access_copy_is_checked_and_stored(library: Path, tmp_path: Path) -> None:
    seen: list[str] = []
    client = _client(article(tmp_path / "oa.pdf").read_bytes(), seen)
    out = enrich_from_library([ref(1)], oa_client=client)
    stored = library / f"{pdf_key(ref(1))}.pdf"
    assert out[0].pdf_path == stored and stored.exists()
    assert (out[0].pdf_source, out[0].source_status) == ("open_access", "found")
    assert not list((library / ".staging").glob("*.pdf"))
    assert "repo.example.org" in seen


def test_wrong_paper_download_is_discarded(library: Path, tmp_path: Path) -> None:
    wrong = article(tmp_path / "wrong.pdf", title=TITLE_B, doi_line=f"doi: {DOI_B}",
                    authors="Ann Poe, Lu Moe")
    out = enrich_from_library([ref(2)], oa_client=_client(wrong.read_bytes(), []))
    assert out[0].pdf_path is None and out[0].pdf_source is None
    assert not list(library.glob("*.pdf"))
    assert not list((library / ".staging").glob("*.pdf"))


def test_library_copy_wins_without_a_download(library: Path) -> None:
    library.mkdir()
    stored = article(library / f"{pdf_key(ref(3))}.pdf")
    seen: list[str] = []
    out = enrich_from_library([ref(3)], oa_client=_client(b"", seen))
    assert out[0].pdf_path == stored and out[0].pdf_source == "library"
    assert seen == []


def test_setting_off_downloads_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("REFCHECK_OA_FETCH", "off")
    seen: list[str] = []
    out = enrich_from_library([ref(4)], oa_client=_client(b"%PDF-1.4", seen))
    assert out[0].pdf_path is None and seen == []
