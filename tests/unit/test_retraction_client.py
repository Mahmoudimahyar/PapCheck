"""Tests for retraction checking (V2)."""

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock

from refcheck.stages.resolve_gaps.retraction_client import (
    RetractionStatus,
    check_retraction_status,
)


class TestRetractionClient:
    @pytest.mark.asyncio
    async def test_crossref_retraction(self) -> None:
        """CrossRef response with retraction -> status=retracted."""
        cr_response = {
            "message": {
                "DOI": "10.1234/test",
                "title": ["Test Paper"],
                "update-to": [
                    {
                        "type": "retraction",
                        "label": "Retraction notice",
                        "DOI": "10.1234/retraction",
                    }
                ],
            }
        }
        mock_response = MagicMock()
        mock_response.json.return_value = cr_response
        mock_response.raise_for_status = MagicMock()

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(return_value=mock_response)

        result = await check_retraction_status(
            "10.1234/test", None, None, client,
        )
        assert result.status == "retracted"
        assert result.source == "crossref"

    @pytest.mark.asyncio
    async def test_crossref_correction(self) -> None:
        """CrossRef response with erratum -> status=corrected."""
        cr_response = {
            "message": {
                "DOI": "10.1234/test",
                "update-to": [
                    {
                        "type": "erratum",
                        "label": "Correction",
                        "DOI": "10.1234/erratum",
                    }
                ],
            }
        }
        mock_response = MagicMock()
        mock_response.json.return_value = cr_response
        mock_response.raise_for_status = MagicMock()

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(return_value=mock_response)

        result = await check_retraction_status(
            "10.1234/test", None, None, client,
        )
        assert result.status == "corrected"

    @pytest.mark.asyncio
    async def test_no_retraction(self) -> None:
        """Clean paper -> status=ok."""
        cr_response = {
            "message": {"DOI": "10.1234/clean", "title": ["Clean Paper"]}
        }
        mock_response = MagicMock()
        mock_response.json.return_value = cr_response
        mock_response.raise_for_status = MagicMock()

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(return_value=mock_response)

        result = await check_retraction_status(
            "10.1234/clean", None, None, client,
        )
        assert result.status == "ok"

    @pytest.mark.asyncio
    async def test_api_error(self) -> None:
        """API error -> status stays ok (graceful fallback)."""
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(
            side_effect=httpx.TimeoutException("timeout"),
        )

        result = await check_retraction_status(
            "10.1234/test", None, None, client,
        )
        # With only crossref failing, falls back to "No retraction info found"
        assert result.status == "ok"

    @pytest.mark.asyncio
    async def test_no_doi_no_pmid(self) -> None:
        """No DOI and no PMID -> status=unknown, no API calls."""
        client = AsyncMock(spec=httpx.AsyncClient)
        result = await check_retraction_status(None, None, None, client)
        assert result.status == "unknown"
        client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_pubmed_retraction(self) -> None:
        """PubMed response with Retracted Publication -> status=retracted."""
        xml = (
            "<PubmedArticle>"
            "<PublicationType>Retracted Publication</PublicationType>"
            "</PubmedArticle>"
        )
        mock_response = MagicMock()
        mock_response.text = xml
        mock_response.raise_for_status = MagicMock()

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(return_value=mock_response)

        result = await check_retraction_status(
            None, None, "12345", client,
        )
        assert result.status == "retracted"
        assert result.source == "pubmed"
