"""Europe PMC abstract fallback and the stub rule of enrichment (HTTP mocked)."""

from collections.abc import Callable, Iterator
from unittest.mock import patch

import httpx
import pytest

from refcheck.models.reference import Reference
from refcheck.stages.resolve_gaps.abstract_quality import choose_abstract, judgeable_abstract
from refcheck.stages.resolve_gaps.enrichment import enrich_references
from refcheck.stages.resolve_gaps.europepmc_client import (
    europepmc_key,
    html_abstract_to_text,
    pick_abstract,
)
from refcheck.stages.verify_claims.source_fallback import mismatch_abstract_document

_FULL = ("Background: Synthetic hydrogels were tested in a rodent wound model. "
         "Methods: Forty animals received either the gel or saline for two weeks. "
         "Results: Closure was faster with the gel and scar width fell by a third. "
         "Conclusions: The gel speeds wound closure without systemic exposure to the drug, "
         "and a larger randomized study in a second species is planned for next year.")
_STUB = "A synthetic stub abstract that is only one short sentence long and no more"


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


def _epmc(doi: str, html: str) -> dict[str, object]:
    return {"resultList": {"result": [{"doi": doi.upper(), "pmid": "123",
                                       "abstractText": html}]}}


class TestParsing:
    def test_html_headings_and_inline_tags(self) -> None:
        raw = "<h4>Abstract</h4><h4>Aims</h4><p>To test <i>p</i> &lt; 0.05.</p>"
        assert html_abstract_to_text(raw) == "Aims: To test p < 0.05."

    def test_pick_requires_same_doi(self) -> None:
        data = _epmc("10.9/other", "<p>Wrong paper.</p>")
        assert pick_abstract(data, "doi:10.1/x") == ""
        assert pick_abstract(_epmc("10.1/X", "<p>Right.</p>"), "doi:10.1/x") == "Right."
        assert pick_abstract({"resultList": {}}, "doi:10.1/x") == ""

    def test_keys(self) -> None:
        assert europepmc_key("https://doi.org/10.1/AB", "5") == "doi:10.1/ab"
        assert europepmc_key(None, "PMID: 42") == "pmid:42"
        assert europepmc_key(None, None) == ""

    def test_stub_rule(self) -> None:
        assert judgeable_abstract(_FULL)
        assert not judgeable_abstract(_STUB)
        assert not judgeable_abstract("Immunosuppression " * 20)  # 360 chars, one sentence
        assert choose_abstract(_STUB, None, [("a", _STUB + "!"), ("b", _FULL)]) == ("b", _FULL)
        assert choose_abstract(None, None, [("a", _STUB)]) == ("a", _STUB)
        assert choose_abstract(_STUB, None, [("a", _STUB + "!")]) is None


class TestEuropePmcFallback:
    async def test_fills_when_other_sources_have_none(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if "ebi.ac.uk" in request.url.host:
                assert request.url.params["query"] == 'DOI:"10.1/old"'
                return httpx.Response(200, json=_epmc("10.1/old", f"<p>{_FULL}</p>"))
            if "semanticscholar" in request.url.host:
                return httpx.Response(200, json=[None])
            return httpx.Response(200, json={"message": {"title": ["X"]}})

        async with _client(handler) as client:
            out = await enrich_references([Reference(id=1, doi="10.1/old")], client)
        assert out[0].abstract_source == "europepmc"
        assert out[0].abstract_text == _FULL
        for req in [r for r in requests if "ebi.ac.uk" in r.url.host]:  # no e-mail sent
            assert "@" not in str(req.url) and "mailto" not in str(req.headers).lower()

    async def test_stub_replaced_by_full_abstract(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if "ebi.ac.uk" in request.url.host:
                return httpx.Response(200, json=_epmc("10.2/stub", f"<p>{_FULL}</p>"))
            if "semanticscholar" in request.url.host:
                return httpx.Response(200, json=[{"abstract": _STUB}])
            return httpx.Response(200, json={"message": {"abstract": f"<jats:p>{_STUB}</jats:p>"}})

        ref = Reference(id=2, doi="10.2/stub", abstract_text=_STUB, abstract_source="crossref")
        async with _client(handler) as client:
            out = await enrich_references([ref], client)
        assert (out[0].abstract_source, out[0].abstract_text) == ("europepmc", _FULL)

    async def test_full_abstract_never_requeried(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert "ebi.ac.uk" not in request.url.host
            assert "semanticscholar" not in request.url.host
            return httpx.Response(200, json={"message": {"title": ["X"]}})

        ref = Reference(id=3, doi="10.3/full", abstract_text=_FULL, abstract_source="pubmed")
        async with _client(handler) as client:
            out = await enrich_references([ref], client)
        assert out[0].abstract_text == _FULL

    async def test_pmid_query_and_api_failure(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if "ebi.ac.uk" in request.url.host:
                seen.append(request.url.params["query"])
                return httpx.Response(500)
            return httpx.Response(200, text="<PubmedArticleSet></PubmedArticleSet>")

        async with _client(handler) as client:
            out = await enrich_references([Reference(id=4, pmid="777")], client)
        assert seen == ["EXT_ID:777 AND SRC:MED"]
        assert out[0].abstract_text is None


def test_europepmc_abstract_stands_in_for_a_wrong_pdf() -> None:
    """The hit was matched on the reference's own DOI/PMID, like PubMed's record."""
    ref = Reference(id=5, doi="10.5/x", abstract_text=_FULL, abstract_source="europepmc",
                    identity_status="mismatch", source_status="found")
    doc = mismatch_abstract_document(ref)
    assert doc is not None and doc.quality_reason == "reference_mismatch"
