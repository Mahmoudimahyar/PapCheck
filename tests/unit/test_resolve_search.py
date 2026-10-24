"""Search candidate picking, 429 backoff and resolver robustness (mocked)."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from refcheck.models.reference import Reference
from refcheck.stages.resolve_gaps.resolver import resolve_gaps

_LK = "refcheck.stages.resolve_gaps.lookups."
_TITLE = "Injectable hydrogels for cartilage repair in osteoarthritic knees"


@pytest.fixture
def _no_enrichment() -> Iterator[None]:
    async def _passthrough(refs: list[Reference], client: object) -> list[Reference]:
        return refs

    with patch(
        "refcheck.stages.resolve_gaps.resolver.enrich_references",
        side_effect=_passthrough,
    ), patch(  # free-full-text hints are tested in test_oa_hints
        "refcheck.stages.resolve_gaps.resolver.add_access_hints",
        AsyncMock(side_effect=lambda refs, _client, _gate=None: refs),
    ):
        yield


@pytest.mark.asyncio
@pytest.mark.usefixtures("_no_enrichment")
async def test_resolver_survives_lookup_exception() -> None:
    ref = Reference(id=1, title=_TITLE)
    with patch(_LK + "pubmed_by_title", AsyncMock(side_effect=RuntimeError("boom"))):
        result = await resolve_gaps([ref])
    assert result[0].source_status == "api_error"


@pytest.mark.asyncio
async def test_send_with_backoff_retries_429() -> None:
    from refcheck.stages.resolve_gaps.http_retry import send_with_backoff

    responses = [httpx.Response(429, headers={"Retry-After": "0"}), httpx.Response(200)]

    async def _send() -> httpx.Response:
        return responses.pop(0)

    resp = await send_with_backoff(_send, base_delay=0.0)
    assert resp.status_code == 200 and not responses


@pytest.mark.asyncio
async def test_send_with_backoff_gives_up() -> None:
    from refcheck.stages.resolve_gaps.http_retry import send_with_backoff

    calls = 0

    async def _send() -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429)

    with patch("refcheck.stages.resolve_gaps.http_retry.asyncio.sleep", AsyncMock()):
        resp = await send_with_backoff(_send, retries=2)
    assert resp.status_code == 429 and calls == 3


def _mock_client(handler: object) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_crossref_title_search_picks_original_over_derivatives() -> None:
    from refcheck.stages.resolve_gaps.crossref_client import search_by_title

    def handler(request: httpx.Request) -> httpx.Response:
        assert "query.bibliographic" in request.url.params
        return httpx.Response(200, json={"message": {"items": [
            {"type": "peer-review", "DOI": "10.1/rev", "title": [f'Review of "{_TITLE}"']},
            {"type": "journal-article", "DOI": "10.1/add", "title": [f"Addendum: {_TITLE}"]},
            {"type": "journal-article", "DOI": "10.1/orig", "title": [_TITLE]},
        ]}})

    async with _mock_client(handler) as client:
        result = await search_by_title(_TITLE, ["J. Smith"], client)
    assert result.found and result.doi == "10.1/orig"


@pytest.mark.asyncio
async def test_pubmed_title_search_picks_original_over_addendum() -> None:
    from refcheck.stages.resolve_gaps.pubmed_client import search_by_title

    def _art(pmid: str, title: str) -> str:
        return (
            f'<PubmedArticle><PMID Version="1">{pmid}</PMID>'
            f"<ArticleTitle>{title}</ArticleTitle></PubmedArticle>"
        )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("esearch.fcgi"):
            return httpx.Response(200, json={"esearchresult": {"idlist": ["2", "1"]}})
        body = _art("2", f"Addendum: {_TITLE}") + _art("1", _TITLE)
        return httpx.Response(200, text=f"<PubmedArticleSet>{body}</PubmedArticleSet>")

    async with _mock_client(handler) as client:
        result = await search_by_title(_TITLE, client)
    assert result.found and result.pmid == "1"
