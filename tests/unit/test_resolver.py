"""Unit tests for gap resolution (all API calls mocked)."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from refcheck.models.reference import Reference
from refcheck.stages.resolve_gaps.resolver import resolve_gaps


def _make_ref(
    ref_id: int,
    title: str = "Test Paper",
    doi: str | None = None,
    pmid: str | None = None,
) -> Reference:
    return Reference(id=ref_id, title=title, doi=doi, pmid=pmid)


def _mock_pubmed_found() -> AsyncMock:
    """Create a mock that returns a found PubMed result."""
    from refcheck.stages.resolve_gaps.pubmed_client import PubMedResult

    mock = AsyncMock()
    mock.return_value = PubMedResult(
        found=True, pmid="12345", title="Test", status="found"
    )
    return mock


def _mock_pubmed_not_found() -> AsyncMock:
    from refcheck.stages.resolve_gaps.pubmed_client import PubMedResult

    mock = AsyncMock()
    mock.return_value = PubMedResult(found=False, status="not_found")
    return mock


def _mock_pubmed_error() -> AsyncMock:
    from refcheck.stages.resolve_gaps.pubmed_client import PubMedResult

    mock = AsyncMock()
    mock.return_value = PubMedResult(found=False, status="api_error")
    return mock


def _mock_crossref_not_found() -> AsyncMock:
    from refcheck.stages.resolve_gaps.crossref_client import CrossRefResult

    mock = AsyncMock()
    mock.return_value = CrossRefResult(found=False, status="not_found")
    return mock


def _mock_s2_not_found() -> AsyncMock:
    from refcheck.stages.resolve_gaps.semantic_scholar_client import S2Result

    mock = AsyncMock()
    mock.return_value = S2Result(found=False, status="not_found")
    return mock


class TestResolveGaps:
    @pytest.mark.asyncio
    async def test_gr01_doi_lookup(self) -> None:
        """GR-01: DOI lookup returns correct metadata."""
        from refcheck.stages.resolve_gaps.crossref_client import CrossRefResult

        ref = _make_ref(1, doi="10.1016/test", title="Test Paper")

        cr_mock = AsyncMock()
        cr_mock.return_value = CrossRefResult(
            found=True, doi="10.1016/test", title="Test Paper",
            url="https://doi.org/10.1016/test", status="found",
        )

        with (
            patch("refcheck.stages.resolve_gaps.resolver.pubmed_by_pmid", _mock_pubmed_not_found()),
            patch("refcheck.stages.resolve_gaps.resolver.pubmed_by_title", _mock_pubmed_not_found()),
            patch("refcheck.stages.resolve_gaps.resolver.crossref_by_doi", cr_mock),
            patch("refcheck.stages.resolve_gaps.resolver.crossref_by_title", _mock_crossref_not_found()),
            patch("refcheck.stages.resolve_gaps.resolver.s2_by_title", _mock_s2_not_found()),
            patch("refcheck.stages.resolve_gaps.resolver.download_pmc_pdf", AsyncMock(return_value=None)),
            patch("refcheck.stages.resolve_gaps.resolver.download_unpaywall_pdf", AsyncMock(return_value=None)),
        ):
            result = await resolve_gaps([ref])
            assert len(result) == 1
            assert result[0].source_status == "found"

    @pytest.mark.asyncio
    async def test_gr02_pmid_lookup(self) -> None:
        """GR-02: PMID lookup returns correct paper."""
        ref = _make_ref(1, pmid="12345678", title="Test")

        with (
            patch("refcheck.stages.resolve_gaps.resolver.pubmed_by_pmid", _mock_pubmed_found()),
            patch("refcheck.stages.resolve_gaps.resolver.pubmed_by_title", _mock_pubmed_not_found()),
            patch("refcheck.stages.resolve_gaps.resolver.crossref_by_doi", _mock_crossref_not_found()),
            patch("refcheck.stages.resolve_gaps.resolver.crossref_by_title", _mock_crossref_not_found()),
            patch("refcheck.stages.resolve_gaps.resolver.s2_by_title", _mock_s2_not_found()),
            patch("refcheck.stages.resolve_gaps.resolver.download_pmc_pdf", AsyncMock(return_value=None)),
            patch("refcheck.stages.resolve_gaps.resolver.download_unpaywall_pdf", AsyncMock(return_value=None)),
        ):
            result = await resolve_gaps([ref])
            assert result[0].source_status == "found"

    @pytest.mark.asyncio
    async def test_gr04_fabricated_reference(self) -> None:
        """GR-04: Fabricated reference returns not_found."""
        ref = _make_ref(1, title="Completely Fabricated Paper That Does Not Exist")

        with (
            patch("refcheck.stages.resolve_gaps.resolver.pubmed_by_pmid", _mock_pubmed_not_found()),
            patch("refcheck.stages.resolve_gaps.resolver.pubmed_by_title", _mock_pubmed_not_found()),
            patch("refcheck.stages.resolve_gaps.resolver.crossref_by_doi", _mock_crossref_not_found()),
            patch("refcheck.stages.resolve_gaps.resolver.crossref_by_title", _mock_crossref_not_found()),
            patch("refcheck.stages.resolve_gaps.resolver.s2_by_title", _mock_s2_not_found()),
        ):
            result = await resolve_gaps([ref])
            assert result[0].source_status == "not_found"

    @pytest.mark.asyncio
    async def test_gr05_api_timeout(self) -> None:
        """GR-05: API timeout returns api_error, not not_found."""
        ref = _make_ref(1, title="Test Paper")

        with (
            patch("refcheck.stages.resolve_gaps.resolver.pubmed_by_pmid", _mock_pubmed_error()),
            patch("refcheck.stages.resolve_gaps.resolver.pubmed_by_title", _mock_pubmed_error()),
            patch("refcheck.stages.resolve_gaps.resolver.crossref_by_doi", _mock_crossref_not_found()),
            patch("refcheck.stages.resolve_gaps.resolver.crossref_by_title", _mock_crossref_not_found()),
            patch("refcheck.stages.resolve_gaps.resolver.s2_by_title", _mock_s2_not_found()),
        ):
            result = await resolve_gaps([ref])
            assert result[0].source_status == "api_error"

    @pytest.mark.asyncio
    async def test_skips_refs_with_pdf(self) -> None:
        """References with existing PDFs are not re-resolved."""
        from pathlib import Path

        ref = _make_ref(1, title="Test")
        ref = ref.model_copy(update={"pdf_path": Path("/tmp/test.pdf")})

        result = await resolve_gaps([ref])
        assert result[0].pdf_path is not None
