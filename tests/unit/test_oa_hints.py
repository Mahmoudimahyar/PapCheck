"""OpenAlex free-full-text hints: parsing, the resolve-stage gate, DB round trip."""

import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from sqlmodel import Session

from refcheck.db import engine as engine_mod
from refcheck.db.converters import db_to_reference, db_to_reference_with_access, reference_to_db
from refcheck.db.reference_repo import get_all_references
from refcheck.models.open_access import OpenAccessHint, ReferenceWithAccess, with_access_hint
from refcheck.models.reference import Reference
from refcheck.stages.resolve_gaps.oa_hints import (
    add_access_hints,
    lacks_full_text,
    parse_openalex_work,
)

_GOLD = {
    "doi": "https://doi.org/10.1/gold",
    "open_access": {"is_oa": True, "oa_status": "hybrid", "oa_url": "https://pub.example/a"},
    "best_oa_location": {"pdf_url": "https://pub.example/a.pdf", "license": "cc-by",
                         "version": "publishedVersion", "landing_page_url": "https://x"},
    "ids": {"pmcid": "https://www.ncbi.nlm.nih.gov/pmc/articles/7654321"},
}
_CLOSED = {"doi": "https://doi.org/10.2/closed",
           "open_access": {"is_oa": False, "oa_status": "closed", "oa_url": None},
           "best_oa_location": None, "ids": {}}


@pytest.fixture(autouse=True)
def _no_disk_cache() -> Iterator[None]:
    with (
        patch("refcheck.stages.resolve_gaps.record_cache.get_cached_api_response",
              return_value=None),
        patch("refcheck.stages.resolve_gaps.record_cache.cache_api_response"),
    ):
        yield


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestParse:
    def test_open_access_work(self) -> None:
        hint = parse_openalex_work(_GOLD, "10.1/GOLD")
        assert hint == OpenAccessHint(
            oa_status="hybrid", oa_url="https://pub.example/a",
            oa_pdf_url="https://pub.example/a.pdf", oa_license="cc-by",
            oa_version="publishedVersion", pmc_id="PMC7654321")

    def test_closed_work_has_no_urls(self) -> None:
        hint = parse_openalex_work(_CLOSED, "10.2/closed")
        assert hint == OpenAccessHint(oa_status="closed")

    def test_other_doi_rejected(self) -> None:
        assert parse_openalex_work(_GOLD, "10.9/other") is None
        assert parse_openalex_work(["not", "a", "work"], "10.1/gold") is None


class TestGate:
    def test_no_pdf_or_mismatch_lacks_full_text(self, tmp_path: Path) -> None:
        pdf = tmp_path / "a.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        assert lacks_full_text(Reference(id=1))
        assert lacks_full_text(Reference(id=1, pdf_path=tmp_path / "missing.pdf"))
        assert lacks_full_text(Reference(id=1, pdf_path=pdf, identity_status="mismatch"))
        assert not lacks_full_text(Reference(id=1, pdf_path=pdf, identity_status="verified"))

    async def test_add_access_hints(self, tmp_path: Path) -> None:
        pdf = tmp_path / "a.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        asked: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.host == "api.openalex.org"
            assert "mailto" not in str(request.url) and "@" not in str(request.url)
            asked.append(request.url.path)
            if request.url.path.endswith("10.1/gold"):
                return httpx.Response(200, json=_GOLD)
            if request.url.path.endswith("10.3/gone"):
                return httpx.Response(404)
            return httpx.Response(503)

        refs = [
            Reference(id=1, doi="10.1/gold"),
            Reference(id=2, doi="10.2/fine", pdf_path=pdf, identity_status="verified"),
            Reference(id=3, doi="10.3/gone"),
            Reference(id=4, doi="10.4/down"),
            Reference(id=5, title="no doi"),
        ]
        async with _client(handler) as client:
            out = await add_access_hints(refs, client)
        assert sorted(asked) == ["/works/doi:10.1/gold", "/works/doi:10.3/gone",
                                 "/works/doi:10.4/down"]
        assert isinstance(out[0], ReferenceWithAccess)
        assert out[0].oa_pdf_url == "https://pub.example/a.pdf"
        assert out[0].pmc_id == "PMC7654321"
        assert out[1:] == refs[1:]  # failures and misses leave references unchanged

    async def test_custom_gate(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("no request expected")

        async with _client(handler) as client:
            out = await add_access_hints([Reference(id=1, doi="10.1/gold")], client,
                                         gate=lambda _ref: False)
        assert out == [Reference(id=1, doi="10.1/gold")]


class TestPersistence:
    def test_round_trip(self, db_session: Session) -> None:
        ref = with_access_hint(Reference(id=7, doi="10.1/gold"), OpenAccessHint(
            oa_status="green", oa_url="https://repo.example/7", oa_version="acceptedVersion"))
        db_session.add(reference_to_db(ref, "s1"))
        db_session.add(reference_to_db(Reference(id=8), "s1"))
        db_session.commit()
        rows = get_all_references(db_session, "s1")
        back = db_to_reference_with_access(rows[0])
        assert (back.oa_status, back.oa_url, back.oa_version) == (
            "green", "https://repo.example/7", "acceptedVersion")
        assert db_to_reference_with_access(rows[1]).oa_status is None
        assert type(db_to_reference(rows[0])) is Reference  # pipeline readers unchanged

    def test_migration_adds_columns(self, tmp_path: Path) -> None:
        db_path = tmp_path / "old.db"
        conn = sqlite3.connect(db_path)
        conn.execute('CREATE TABLE "references" (id INTEGER PRIMARY KEY)')
        for table in ("claims", "verifications", "sessions"):
            conn.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY)')
        conn.commit()
        conn.close()
        engine_mod._migrate_add_columns(db_path)
        conn = sqlite3.connect(db_path)
        cols = {row[1] for row in conn.execute('PRAGMA table_info("references")')}
        conn.close()
        assert {"oa_status", "oa_url", "oa_pdf_url", "oa_license", "oa_version"} <= cols
