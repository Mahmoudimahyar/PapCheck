"""Opt-in open-access fetch (V5.8, G3): off by default, never live under pytest, link
discovery (Unpaywall with the contact e-mail only there, Europe PMC / PMC), download
checks. Every request goes to an httpx.MockTransport."""

from collections.abc import Callable
from pathlib import Path
from urllib.parse import unquote

import httpx
import pytest

from refcheck.library.oa_fetch import download_pdf, fetch_open_access
from refcheck.library.oa_settings import OaSettings, load_oa_settings
from refcheck.library.oa_sources import oa_links
from tests.unit.rematch_fakes import DOI_A, ref

EMAIL = "tester@example.org"
PDF = b"%PDF-1.7\n" + b"0" * 2000
Handler = Callable[[httpx.Request], httpx.Response]


def _client(routes: dict[str, Handler], seen: list[httpx.Request]) -> httpx.Client:
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        handler = routes.get(request.url.host)
        return handler(request) if handler else httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=True)


def _unpaywall(_: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={
        "best_oa_location": {"url_for_pdf": "https://repo.example.org/a.pdf"},
        "oa_locations": [{"url_for_pdf": "https://repo.example.org/a.pdf"},
                         {"url_for_pdf": "ftp://old.example.org/a.pdf"}, {"url": "x"}]})


def _epmc(doi: str = DOI_A) -> Handler:
    def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"resultList": {"result": [{
            "doi": doi, "pmcid": "PMC123", "isOpenAccess": "Y",
            "fullTextUrlList": {"fullTextUrl": [
                {"url": "https://epmc.example.org/x.pdf", "documentStyle": "pdf",
                 "availabilityCode": "OA"},
                {"url": "https://pay.example.org/x.pdf", "documentStyle": "pdf",
                 "availabilityCode": "S"}]}}]}})
    return handle


def _pdf(content_type: str = "application/pdf", body: bytes = PDF) -> Handler:
    return lambda _: httpx.Response(200, headers={"content-type": content_type}, content=body)


def test_settings_default_off_and_email_only_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("REFCHECK_OA_FETCH", "REFCHECK_CONTACT_EMAIL", "REFCHECK_OA_MAX_MB"):
        monkeypatch.delenv(name, raising=False)
    assert load_oa_settings() == OaSettings()
    monkeypatch.setenv("REFCHECK_OA_FETCH", "on")
    monkeypatch.setenv("REFCHECK_CONTACT_EMAIL", "not-an-address")
    monkeypatch.setenv("REFCHECK_OA_MAX_MB", "2")
    settings = load_oa_settings()
    assert settings.enabled and settings.contact_email == ""
    assert settings.max_bytes == 2 * 1024 * 1024


def test_disabled_fetch_sends_nothing(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    client = _client({"api.unpaywall.org": _unpaywall}, seen)
    assert fetch_open_access(ref(1), tmp_path, lambda p: True, OaSettings(), client) is None
    assert seen == []


def test_no_live_fetch_under_pytest(tmp_path: Path) -> None:
    settings = OaSettings(enabled=True, contact_email=EMAIL)
    assert fetch_open_access(ref(1), tmp_path, lambda p: True, settings) is None


def test_links_from_unpaywall_and_europe_pmc(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    client = _client({"api.unpaywall.org": _unpaywall, "www.ebi.ac.uk": _epmc()}, seen)
    links = oa_links(client, ref(1), EMAIL)
    assert [(link.source, link.url) for link in links] == [
        ("unpaywall", "https://repo.example.org/a.pdf"),
        ("europepmc", "https://epmc.example.org/x.pdf"),
        ("europepmc", "https://europepmc.org/articles/PMC123?pdf=render"),
        ("pmc", "https://pmc.ncbi.nlm.nih.gov/articles/PMC123/pdf/")]
    hosts_with_email = {r.url.host for r in seen if EMAIL in unquote(str(r.url))}
    assert hosts_with_email == {"api.unpaywall.org"}


def test_no_email_skips_unpaywall_and_other_doi_is_ignored() -> None:
    seen: list[httpx.Request] = []
    client = _client({"api.unpaywall.org": _unpaywall,
                       "www.ebi.ac.uk": _epmc("10.5555/another.999")}, seen)
    assert oa_links(client, ref(1), "") == []
    assert {r.url.host for r in seen} == {"www.ebi.ac.uk"}


def test_lookup_errors_yield_no_links() -> None:
    seen: list[httpx.Request] = []
    client = _client({"api.unpaywall.org": lambda _: httpx.Response(500),
                      "www.ebi.ac.uk": lambda _: httpx.Response(200, text="<html>")}, seen)
    assert oa_links(client, ref(1), EMAIL) == []


@pytest.mark.parametrize(("handler", "reason"), [
    (_pdf("text/html", b"<html>login</html>"), "type:text/html"),
    (_pdf(body=b"GIF89a" + b"0" * 100), "not_a_pdf"),
    (_pdf(body=PDF * 3), "too_large"),
    (lambda _: httpx.Response(200, headers={"content-length": "99999999"}, content=PDF),
     "too_large"),
    (lambda _: httpx.Response(403), "http_403"),
])
def test_download_checks(tmp_path: Path, handler: Handler, reason: str) -> None:
    client = _client({"repo.example.org": handler}, [])
    out = download_pdf(client, "https://repo.example.org/a.pdf", tmp_path / "a.pdf", 5000)
    assert out.path is None and out.reason == reason
    assert not (tmp_path / "a.pdf").exists()


def test_download_saves_a_pdf(tmp_path: Path) -> None:
    client = _client({"repo.example.org": _pdf("application/pdf; charset=binary")}, [])
    out = download_pdf(client, "https://repo.example.org/a.pdf", tmp_path / "a.pdf", 5000)
    assert out.path == tmp_path / "a.pdf" and out.path.read_bytes() == PDF


def test_refused_download_is_deleted_and_next_candidate_tried(tmp_path: Path) -> None:
    client = _client({"api.unpaywall.org": _unpaywall, "www.ebi.ac.uk": _epmc(),
                      "repo.example.org": _pdf(), "epmc.example.org": _pdf()}, [])
    checked: list[Path] = []

    def accept(path: Path) -> bool:
        checked.append(path)
        return len(checked) == 2  # the first download is "another paper"

    settings = OaSettings(enabled=True, contact_email=EMAIL)
    fetched = fetch_open_access(ref(1), tmp_path / "staging", accept, settings, client)
    assert fetched is not None and fetched.source == "europepmc"
    assert not checked[0].exists() and fetched.path.exists()
