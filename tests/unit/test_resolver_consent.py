"""V5.8 G3: stage 4 downloads open-access PDFs only with consent (REFCHECK_OA_FETCH=on),
never under pytest; otherwise a found reference keeps its journal link. All HTTP mocked."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from refcheck.models.reference import Reference
from refcheck.stages.resolve_gaps import resolver
from refcheck.stages.resolve_gaps.resolver import resolve_gaps

_RS = "refcheck.stages.resolve_gaps.resolver."
FOUND = {"source_status": "found", "doi": "10.1000/xyz", "pmc_id": "PMC1"}


@pytest.fixture
def mocks(tmp_path: Path) -> Iterator[tuple[AsyncMock, AsyncMock]]:
    pmc = AsyncMock(return_value=tmp_path / "oa.pdf")
    unpaywall = AsyncMock(return_value=None)
    with patch(_RS + "try_pubmed", AsyncMock(return_value=dict(FOUND))), \
            patch(_RS + "try_crossref", AsyncMock(return_value=None)), \
            patch(_RS + "try_semantic_scholar", AsyncMock(return_value=None)), \
            patch(_RS + "download_pmc_pdf", pmc), \
            patch(_RS + "download_unpaywall_pdf", unpaywall), \
            patch(_RS + "enrich_references", AsyncMock(side_effect=lambda refs, _c: refs)), \
            patch(_RS + "apply_identity_checks", side_effect=lambda refs: refs), \
            patch(_RS + "add_access_hints",
                  AsyncMock(side_effect=lambda refs, _client, _gate=None: refs)):
        yield pmc, unpaywall


async def test_no_download_without_consent(monkeypatch: pytest.MonkeyPatch,
                                           mocks: tuple[AsyncMock, AsyncMock]) -> None:
    monkeypatch.delenv("REFCHECK_OA_FETCH", raising=False)
    result = (await resolve_gaps([Reference(id=1, title="A paper")]))[0]
    mocks[0].assert_not_awaited()
    mocks[1].assert_not_awaited()
    assert result.pdf_path is None and result.journal_url == "https://doi.org/10.1000/xyz"


async def test_consent_is_still_refused_under_pytest(monkeypatch: pytest.MonkeyPatch,
                                                     mocks: tuple[AsyncMock, AsyncMock]) -> None:
    monkeypatch.setenv("REFCHECK_OA_FETCH", "on")
    assert not resolver.downloads_allowed()
    await resolve_gaps([Reference(id=1, title="A paper")])
    mocks[0].assert_not_awaited()


async def test_download_with_consent(monkeypatch: pytest.MonkeyPatch,
                                     mocks: tuple[AsyncMock, AsyncMock]) -> None:
    monkeypatch.setenv("REFCHECK_OA_FETCH", "on")
    monkeypatch.setattr(resolver, "under_pytest", lambda: False)
    result = (await resolve_gaps([Reference(id=1, title="A paper")]))[0]
    mocks[0].assert_awaited_once()
    assert result.pdf_source == "open_access" and result.journal_url is None
