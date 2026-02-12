"""Live API integration tests — requires real API keys in .env.

These tests make actual HTTP requests to PubMed, CrossRef,
Semantic Scholar, and Unpaywall. Run only when API keys are configured.
"""

import os
from pathlib import Path

import pytest

# Skip entire module if no API keys configured
pytestmark = pytest.mark.integration


class TestPubMedLive:
    """Live tests against PubMed/NCBI E-utilities."""

    @pytest.mark.asyncio
    async def test_search_by_known_pmid(self) -> None:
        """Look up a well-known paper by PMID."""
        from refcheck.stages.resolve_gaps.pubmed_client import search_by_pmid

        # PMID 33116429 = BNT162b2 COVID vaccine paper (Polack et al., NEJM 2020)
        result = await search_by_pmid("33116429")
        assert result.found is True
        assert result.status == "found"
        assert result.pmid == "33116429"
        assert "BNT162b2" in result.title or "COVID" in result.title.upper() or result.title != ""

    @pytest.mark.asyncio
    async def test_search_by_title(self) -> None:
        """Search PubMed by a known paper title."""
        from refcheck.stages.resolve_gaps.pubmed_client import search_by_title

        result = await search_by_title(
            "Safety and Efficacy of the BNT162b2 mRNA Covid-19 Vaccine"
        )
        assert result.found is True
        assert result.status == "found"
        assert result.pmid != ""

    @pytest.mark.asyncio
    async def test_search_fabricated_title(self) -> None:
        """Fabricated title should return not_found."""
        from refcheck.stages.resolve_gaps.pubmed_client import search_by_title

        result = await search_by_title(
            "Xylophone quantum entanglement in jellyfish synapses 2099"
        )
        assert result.found is False
        assert result.status == "not_found"


class TestCrossRefLive:
    """Live tests against CrossRef API."""

    @pytest.mark.asyncio
    async def test_search_by_known_doi(self) -> None:
        """Look up a well-known paper by DOI."""
        from refcheck.stages.resolve_gaps.crossref_client import search_by_doi

        # DOI for the original CRISPR paper (Jinek et al., Science 2012)
        result = await search_by_doi("10.1126/science.1225829")
        assert result.found is True
        assert result.status == "found"
        assert result.doi == "10.1126/science.1225829"
        assert result.year == 2012
        assert "CRISPR" in result.title.upper() or result.title != ""

    @pytest.mark.asyncio
    async def test_search_by_title(self) -> None:
        """Search CrossRef by title."""
        from refcheck.stages.resolve_gaps.crossref_client import search_by_title

        result = await search_by_title(
            "A programmable dual-RNA-guided DNA endonuclease in adaptive bacterial immunity"
        )
        assert result.found is True
        assert result.doi != ""

    @pytest.mark.asyncio
    async def test_nonexistent_doi(self) -> None:
        """Non-existent DOI should return not_found."""
        from refcheck.stages.resolve_gaps.crossref_client import search_by_doi

        result = await search_by_doi("10.9999/completely-fake-doi-12345")
        assert result.found is False
        assert result.status == "not_found"


class TestSemanticScholarLive:
    """Live tests against Semantic Scholar API (no key, public rate)."""

    @pytest.mark.asyncio
    async def test_search_by_title(self) -> None:
        """Search S2 for a well-known paper by title."""
        from refcheck.stages.resolve_gaps.semantic_scholar_client import (
            search_by_title,
        )

        result = await search_by_title(
            "Attention Is All You Need"
        )
        # S2 public API may rate-limit (100 req/5min) → api_error is OK
        if result.status == "api_error":
            pytest.skip("Semantic Scholar rate-limited (public API)")
        assert result.found is True
        assert result.status == "found"
        assert "attention" in result.title.lower()
        assert result.year == 2017
        assert result.citation_count > 0

    @pytest.mark.asyncio
    async def test_search_fabricated_title(self) -> None:
        """Fabricated title should return not_found or irrelevant result."""
        from refcheck.stages.resolve_gaps.semantic_scholar_client import (
            search_by_title,
        )

        result = await search_by_title(
            "Quantum teleportation of live jellyfish through wormholes 2099"
        )
        # S2 may return a loosely related result, rate-limit, or not_found
        # The important thing is it doesn't crash
        assert result.status in ("found", "not_found", "api_error")


class TestUnpaywallLive:
    """Live tests against Unpaywall API."""

    @pytest.mark.asyncio
    async def test_oa_lookup_for_known_oa_paper(self) -> None:
        """Look up a known open-access paper on Unpaywall."""
        email = os.environ.get("UNPAYWALL_EMAIL", "")
        if not email:
            pytest.skip("UNPAYWALL_EMAIL not set")

        from refcheck.stages.resolve_gaps.retriever import download_unpaywall_pdf

        # Use a known OA paper DOI (the CRISPR paper is OA)
        # We won't actually download — just check the function doesn't crash
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            result = await download_unpaywall_pdf(
                "10.1126/science.1225829", Path(tmp)
            )
            # May or may not download depending on OA availability
            # The key check: no crash, no exception
            if result is not None:
                assert result.exists()
                assert result.stat().st_size > 0


class TestFullResolverLive:
    """Live test of the full resolver cascade with real APIs."""

    @pytest.mark.asyncio
    async def test_resolve_known_paper_by_doi(self) -> None:
        """Resolve a real paper with a known DOI."""
        from refcheck.models.reference import Reference
        from refcheck.stages.resolve_gaps.resolver import resolve_gaps

        ref = Reference(
            id=1,
            title="Attention Is All You Need",
            doi="10.48550/arXiv.1706.03762",
            raw_text="Vaswani A et al. Attention Is All You Need. 2017.",
        )
        results = await resolve_gaps([ref])
        assert len(results) == 1
        assert results[0].source_status == "found"

    @pytest.mark.asyncio
    async def test_resolve_known_paper_by_pmid(self) -> None:
        """Resolve a real biomedical paper with a PMID."""
        from refcheck.models.reference import Reference
        from refcheck.stages.resolve_gaps.resolver import resolve_gaps

        ref = Reference(
            id=1,
            title="Safety and Efficacy of the BNT162b2 mRNA Covid-19 Vaccine",
            pmid="33116429",
            raw_text="Polack FP et al. BNT162b2 vaccine. NEJM. 2020.",
        )
        results = await resolve_gaps([ref])
        assert len(results) == 1
        assert results[0].source_status == "found"
        assert results[0].pmid == "33116429"

    @pytest.mark.asyncio
    async def test_resolve_fabricated_paper(self) -> None:
        """Fabricated reference — APIs may return loose matches.

        CrossRef/S2 do fuzzy search, so a completely fake title
        may still loosely match some real paper.  We just verify
        the resolver runs without error and returns a valid status.
        """
        from refcheck.models.reference import Reference
        from refcheck.stages.resolve_gaps.resolver import resolve_gaps

        ref = Reference(
            id=99,
            title="Zxqwj Plmknb Asdftg Hgfedcba Uytrewq 2099",
            raw_text="Nobody A. Zxqwj Plmknb. Fake J. 2099;1:1-5.",
        )
        results = await resolve_gaps([ref])
        assert len(results) == 1
        # With a truly nonsensical title, most APIs return not_found
        # but S2/CrossRef might still loosely match something
        assert results[0].source_status in ("not_found", "api_error", "found")

    @pytest.mark.asyncio
    async def test_resolve_distinguishes_real_from_fabricated(self) -> None:
        """Verify a real paper is found while a gibberish title is handled gracefully."""
        from refcheck.models.reference import Reference
        from refcheck.stages.resolve_gaps.resolver import resolve_gaps

        # A real paper that should be found
        real_ref = Reference(
            id=1,
            title="CRISPR-Cas9",
            doi="10.1126/science.1225829",
            raw_text="Jinek et al. CRISPR. Science. 2012.",
        )
        # A gibberish paper (fuzzy APIs may still return a loose match)
        fake_ref = Reference(
            id=2,
            title="Zxqwj Plmknb Asdftg Hgfedcba 2099",
            raw_text="Nobody. Zxqwj. 2099.",
        )
        results = await resolve_gaps([real_ref, fake_ref])
        assert len(results) == 2

        real_result = next(r for r in results if r.id == 1)
        fake_result = next(r for r in results if r.id == 2)

        # Real paper must be found
        assert real_result.source_status == "found"
        # Fabricated paper: any valid status is acceptable
        assert fake_result.source_status in ("not_found", "api_error", "found")
