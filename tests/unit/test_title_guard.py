"""Title-similarity guard on search hits (all network mocked)."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from refcheck.models.reference import Reference
from refcheck.stages.resolve_gaps.crossref_client import CrossRefResult
from refcheck.stages.resolve_gaps.lookups import (
    try_crossref,
    try_pubmed,
    try_semantic_scholar,
)
from refcheck.stages.resolve_gaps.pubmed_client import PubMedResult
from refcheck.stages.resolve_gaps.resolver import resolve_gaps
from refcheck.stages.resolve_gaps.semantic_scholar_client import S2Result
from refcheck.stages.resolve_gaps.title_guard import (
    TITLE_SIMILARITY_THRESHOLD,
    accept_search_hit,
    normalize_title,
    title_similarity,
)

_LK = "refcheck.stages.resolve_gaps.lookups."
_TITLE = "Injectable hydrogels for cartilage repair in osteoarthritic knees"
_WRONG = "Deep learning for retinal image segmentation"


class TestNormalizeAndSimilarity:
    def test_normalize_strips_markup_accents_punctuation(self) -> None:
        assert normalize_title("<i>In vivo</i> Café-Study: A&amp;B.") == "in vivo cafe study a b"

    def test_identical_titles_score_one(self) -> None:
        assert title_similarity(_TITLE, _TITLE.upper() + ".") == 1.0

    def test_unrelated_titles_score_low(self) -> None:
        assert title_similarity(_TITLE, _WRONG) < TITLE_SIMILARITY_THRESHOLD

    def test_empty_titles_score_zero(self) -> None:
        assert title_similarity("", _TITLE) == 0.0


class TestAcceptSearchHit:
    def test_accepts_close_title(self) -> None:
        assert accept_search_hit(_TITLE, None, _TITLE + ": a review", "", "PubMed")

    def test_rejects_wrong_title(self) -> None:
        assert not accept_search_hit(_TITLE, None, _WRONG, "10.1/x", "PubMed")

    def test_accepts_doi_match_despite_title(self) -> None:
        assert accept_search_hit(
            _TITLE, "https://doi.org/10.1000/ABC", _WRONG, "10.1000/abc", "CrossRef",
        )


class TestGuardedLookups:
    @pytest.mark.asyncio
    async def test_pubmed_title_hit_rejected(self) -> None:
        ref = Reference(id=1, title=_TITLE)
        hit = PubMedResult(found=True, pmid="999", title=_WRONG, status="found")
        with patch(_LK + "pubmed_by_title", AsyncMock(return_value=hit)):
            assert await try_pubmed(ref, AsyncMock(spec=httpx.AsyncClient)) is None

    @pytest.mark.asyncio
    async def test_pubmed_pmid_lookup_not_guarded(self) -> None:
        ref = Reference(id=1, title=_TITLE, pmid="123")
        hit = PubMedResult(
            found=True, pmid="123", title=_WRONG, abstract="A" * 80, status="found",
        )
        with patch(_LK + "pubmed_by_pmid", AsyncMock(return_value=hit)):
            updates = await try_pubmed(ref, AsyncMock(spec=httpx.AsyncClient))
        assert updates is not None
        assert updates["source_status"] == "found"
        assert updates["abstract_source"] == "pubmed"

    @pytest.mark.asyncio
    async def test_crossref_title_hit_rejected(self) -> None:
        ref = Reference(id=1, title=_TITLE)
        hit = CrossRefResult(found=True, title=_WRONG, doi="10.1/x", status="found")
        with patch(_LK + "crossref_by_title", AsyncMock(return_value=hit)):
            assert await try_crossref(ref, AsyncMock(spec=httpx.AsyncClient)) is None

    @pytest.mark.asyncio
    async def test_s2_close_hit_accepted_with_abstract(self) -> None:
        ref = Reference(id=1, title=_TITLE)
        hit = S2Result(
            found=True, title=_TITLE, doi="10.2/y", pmid="77",
            abstract="Background text. " * 5, status="found",
        )
        with patch(_LK + "s2_by_title", AsyncMock(return_value=hit)):
            updates = await try_semantic_scholar(ref, AsyncMock(spec=httpx.AsyncClient))
        assert updates is not None
        assert updates["doi"] == "10.2/y"
        assert updates["pmid"] == "77"
        assert updates["abstract_source"] == "semantic_scholar"


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
async def test_resolver_treats_all_wrong_hits_as_not_found() -> None:
    """Every API returns a wrong paper -> not_found, no PDF download."""
    ref = Reference(id=1, title=_TITLE)
    pm = PubMedResult(found=True, pmid="9", pmc_id="PMC9", title=_WRONG, status="found")
    cr = CrossRefResult(found=True, title=_WRONG, doi="10.9/z", status="found")
    s2 = S2Result(found=True, title=_WRONG, doi="10.9/z", status="found")
    pmc = AsyncMock(return_value=None)
    with (
        patch(_LK + "pubmed_by_title", AsyncMock(return_value=pm)),
        patch(_LK + "crossref_by_title", AsyncMock(return_value=cr)),
        patch(_LK + "s2_by_title", AsyncMock(return_value=s2)),
        patch("refcheck.stages.resolve_gaps.resolver.download_pmc_pdf", pmc),
    ):
        result = await resolve_gaps([ref])
    assert result[0].source_status == "not_found"
    assert result[0].pmid is None
    assert result[0].doi is None
    pmc.assert_not_called()


class TestNoticeHits:
    def test_addendum_with_same_title_rejected(self) -> None:
        hit = f"Addendum: {_TITLE}"
        assert title_similarity(_TITLE, hit) == 1.0  # token_set alone would accept
        assert not accept_search_hit(_TITLE, None, hit, "", "PubMed")

    def test_notice_reference_may_match_notice(self) -> None:
        ref = f"Retraction notice to: {_TITLE}"
        assert accept_search_hit(ref, None, ref, "", "CrossRef")

    def test_correction_prefixed_paper_titles_both_sides(self) -> None:
        title = "Correction of hallux valgus deformity by distal osteotomy"
        assert accept_search_hit(title, None, title, "", "PubMed")


class TestDerivativeWorks:
    def test_review_of_and_recommendation_prefixes(self) -> None:
        from refcheck.stages.resolve_gaps.title_guard import is_derivative_of

        assert is_derivative_of(_TITLE, f'Review of "{_TITLE}"')
        assert is_derivative_of(_TITLE, f"Faculty Opinions recommendation of {_TITLE}.")
        assert not is_derivative_of(_TITLE, f"{_TITLE}: a systematic review")
        assert not is_derivative_of(_TITLE, _TITLE)

    def test_pick_best_hit_skips_derivatives(self) -> None:
        from refcheck.stages.resolve_gaps.title_guard import pick_best_hit

        hits = [f"Addendum: {_TITLE}", f'Review of "{_TITLE}"', _TITLE, _WRONG]
        assert pick_best_hit(_TITLE, hits, lambda h: h) == _TITLE
        assert pick_best_hit(_TITLE, [_WRONG], lambda h: h) == _WRONG
        assert pick_best_hit(_TITLE, [], lambda h: h) is None


def test_api_titles_are_stripped_of_markup() -> None:
    from refcheck.stages.resolve_gaps.crossref_client import _parse_crossref_work
    from refcheck.stages.resolve_gaps.semantic_scholar_client import _parse_s2_paper

    cr = _parse_crossref_work({"message": {"title": [
        "<p>Multifunctional Synthetic Hydrogel Carrying Engineered "
        "High-Secreting Cells</p>"], "DOI": "10.1/x"}})
    assert cr.title == ("Multifunctional Synthetic Hydrogel Carrying Engineered "
                        "High-Secreting Cells")
    s2 = _parse_s2_paper({"title": "CO<sub>2</sub> &amp; islets"})
    assert s2.title == "CO2 & islets"
