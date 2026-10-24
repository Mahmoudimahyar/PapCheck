"""Abstract parsing, batched abstract/retraction enrichment (network mocked)."""

import json
from collections.abc import Callable, Iterator
from unittest.mock import patch

import httpx
import pytest

from refcheck.models.reference import Reference
from refcheck.stages.resolve_gaps.crossref_client import _parse_crossref_work
from refcheck.stages.resolve_gaps.enrichment import enrich_references
from refcheck.stages.resolve_gaps.markup import (
    parse_pubmed_abstract,
    parse_pubmed_year,
    split_pubmed_articles,
    strip_jats,
)
from refcheck.stages.resolve_gaps.pubmed_batch import parse_pubmed_record
from refcheck.stages.resolve_gaps.pubmed_client import _parse_pubmed_xml
from refcheck.stages.resolve_gaps.semantic_scholar_client import _parse_s2_paper

_ARTICLE = """<PubmedArticle><MedlineCitation Status="MEDLINE">
<PMID Version="1">111</PMID>
<DateCompleted><Year>2021</Year></DateCompleted>
<Article><Journal><JournalIssue><PubDate><Year>2019</Year><Month>Mar</Month></PubDate>
</JournalIssue></Journal>
<ArticleTitle>Hydrogel <i>scaffolds</i> for cartilage.</ArticleTitle>
<Abstract>
<AbstractText Label="BACKGROUND" NlmCategory="BACKGROUND">Cartilage heals poorly.</AbstractText>
<AbstractText Label="RESULTS" NlmCategory="RESULTS">Repair improved by 30%
 (<i>p</i> &lt; 0.05).</AbstractText>
</Abstract>
<PublicationTypeList><PublicationType UI="D016428">Journal Article</PublicationType>
</PublicationTypeList></Article>
<CommentsCorrectionsList><CommentsCorrections RefType="RetractionIn">
<RefSource>J X. 2022</RefSource></CommentsCorrections></CommentsCorrectionsList>
</MedlineCitation><PubmedData><ArticleIdList>
<ArticleId IdType="pubmed">111</ArticleId><ArticleId IdType="doi">10.1/hydro</ArticleId>
<ArticleId IdType="pmc">PMC555</ArticleId></ArticleIdList></PubmedData></PubmedArticle>"""

_PLAIN_ARTICLE = """<PubmedArticle><MedlineCitation><PMID Version="1">222</PMID>
<Article><ArticleTitle>Plain paper</ArticleTitle><Abstract>
<AbstractText>An unlabelled abstract that mentions an erratum in passing only.</AbstractText>
</Abstract></Article></MedlineCitation></PubmedArticle>"""


class TestMarkupParsing:
    def test_labelled_abstract_parts_joined(self) -> None:
        text = parse_pubmed_abstract(_ARTICLE)
        assert text == (
            "BACKGROUND: Cartilage heals poorly.\n"
            "RESULTS: Repair improved by 30% (p < 0.05)."
        )

    def test_unlabelled_abstract(self) -> None:
        assert parse_pubmed_abstract(_PLAIN_ARTICLE).startswith("An unlabelled abstract")

    def test_no_abstract(self) -> None:
        assert parse_pubmed_abstract("<PubmedArticle></PubmedArticle>") == ""

    def test_year_from_pubdate_not_date_completed(self) -> None:
        assert parse_pubmed_year(_ARTICLE) == 2019
        medline = "<PubDate><MedlineDate>2018 Dec-2019 Jan</MedlineDate></PubDate>"
        assert parse_pubmed_year(medline) == 2018

    def test_split_articles(self) -> None:
        xml = f"<PubmedArticleSet>{_ARTICLE}{_PLAIN_ARTICLE}</PubmedArticleSet>"
        arts = split_pubmed_articles(xml)
        assert set(arts) == {"111", "222"}

    def test_strip_jats(self) -> None:
        jats = (
            "<jats:title>Abstract</jats:title><jats:sec><jats:title>Aims</jats:title>"
            "<jats:p>To test &amp; measure.</jats:p></jats:sec>"
        )
        assert strip_jats(jats) == "Aims: To test & measure."


class TestClientParsers:
    def test_pubmed_client_sets_abstract_title_year(self) -> None:
        result = _parse_pubmed_xml(_ARTICLE, "111")
        assert result.title == "Hydrogel scaffolds for cartilage."
        assert result.year == 2019
        assert result.abstract.startswith("BACKGROUND:")
        assert result.pmc_id == "PMC555"

    def test_s2_parser_sets_abstract_and_pmid(self) -> None:
        paper = {
            "title": "T", "year": 2020, "abstract": " Text. ",
            "externalIds": {"DOI": "10.1/a", "PubMed": "42"},
        }
        result = _parse_s2_paper(paper)
        assert (result.abstract, result.pmid, result.doi) == ("Text.", "42", "10.1/a")

    def test_crossref_parser_sets_abstract(self) -> None:
        result = _parse_crossref_work({"message": {
            "title": ["T"], "DOI": "10.1/a", "abstract": "<jats:p>Hello</jats:p>",
        }})
        assert result.abstract == "Hello"

    def test_pubmed_record_retraction_structured(self) -> None:
        assert parse_pubmed_record("111", _ARTICLE).retraction.status == "retracted"
        # free-text "erratum" in an abstract must not flag a correction
        assert parse_pubmed_record("222", _PLAIN_ARTICLE).retraction.status == "ok"


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


_LONG = "This abstract is long enough to be used as the source abstract unit."


class TestEnrichReferences:
    @pytest.mark.asyncio
    async def test_pubmed_batch_s2_and_crossref(self) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(f"{request.method} {request.url.host}")
            if "eutils" in request.url.host:
                assert "111" in request.content.decode()
                return httpx.Response(200, text=f"<PubmedArticleSet>{_ARTICLE}</PubmedArticleSet>")
            if "semanticscholar" in request.url.host:
                ids = json.loads(request.content)["ids"]
                # ref 3's stored abstract is a stub, so a full one is looked for
                assert ids == ["DOI:10.2/s2", "DOI:10.3/cr"]
                return httpx.Response(200, json=[{"abstract": _LONG}, None])
            if "ebi.ac.uk" in request.url.host:
                return httpx.Response(200, json={"resultList": {"result": []}})
            doi = request.url.path.split("/works/")[1]
            msg: dict[str, object] = {"DOI": doi, "title": ["X"]}
            if doi == "10.3/cr":
                msg["updated-by"] = [{"type": "retraction", "DOI": "10.3/notice"}]
            return httpx.Response(200, json={"message": msg})

        refs = [
            Reference(id=1, pmid="111"),
            Reference(id=2, doi="10.2/s2"),
            Reference(id=3, doi="10.3/cr", abstract_text=_LONG, abstract_source="pdf"),
        ]
        async with _client(handler) as client:
            out = await enrich_references(refs, client)

        assert out[0].abstract_source == "pubmed"
        assert out[0].abstract_text and out[0].abstract_text.startswith("BACKGROUND:")
        assert out[0].retraction_status == "retracted"
        assert out[0].pmc_id == "PMC555" and out[0].doi == "10.1/hydro"
        assert out[1].abstract_source == "semantic_scholar"
        assert out[1].retraction_status == "ok"
        assert out[2].abstract_source == "pdf"  # existing abstract never overwritten
        assert out[2].retraction_status == "retracted"
        assert sum("eutils" in c for c in calls) == 1  # one batched efetch

    @pytest.mark.asyncio
    async def test_api_failures_leave_references_unchanged(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        refs = [Reference(id=1, pmid="111", doi="10.1/a")]
        async with _client(handler) as client:
            out = await enrich_references(refs, client)
        assert out[0].abstract_text is None
        assert out[0].retraction_status == "unknown"

    @pytest.mark.asyncio
    async def test_crossref_abstract_used_last(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if "semanticscholar" in request.url.host:
                return httpx.Response(200, json=[None])
            return httpx.Response(200, json={"message": {
                "title": ["X"], "abstract": f"<jats:p>{_LONG}</jats:p>",
            }})

        async with _client(handler) as client:
            out = await enrich_references([Reference(id=1, doi="10.5/q")], client)
        assert out[0].abstract_source == "crossref"
        assert out[0].abstract_text == _LONG

    @pytest.mark.asyncio
    async def test_no_identifiers_no_requests(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("no request expected")

        refs = [Reference(id=1, title="Something")]
        async with _client(handler) as client:
            assert await enrich_references(refs, client) == refs
