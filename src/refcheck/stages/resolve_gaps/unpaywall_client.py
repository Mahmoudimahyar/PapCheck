"""Unpaywall API client for finding open-access PDFs."""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_EMAIL = "refcheck@example.com"
_TIMEOUT = 15


async def find_open_access_pdf(
    doi: str,
    email: str | None = None,
) -> str | None:
    """Query api.unpaywall.org for a legal OA PDF URL.

    Returns the best available PDF URL, or None if not found.
    """
    contact_email = email or os.environ.get("UNPAYWALL_EMAIL", _DEFAULT_EMAIL)
    url = f"https://api.unpaywall.org/v2/{doi}"
    params = {"email": contact_email}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                logger.debug(
                    "Unpaywall returned %d for DOI %s", resp.status_code, doi,
                )
                return None
            data = resp.json()
            return _extract_best_pdf_url(data, doi)
    except httpx.TimeoutException:
        logger.warning("Unpaywall timeout for DOI %s", doi)
        return None
    except Exception as exc:
        logger.warning("Unpaywall error for DOI %s: %s", doi, exc)
        return None


def _extract_best_pdf_url(
    data: dict[str, object], doi: str,
) -> str | None:
    """Extract the best PDF URL from Unpaywall response."""
    best_oa = data.get("best_oa_location")
    if isinstance(best_oa, dict):
        pdf_url = best_oa.get("url_for_pdf")
        if pdf_url and isinstance(pdf_url, str):
            logger.info("Unpaywall found OA PDF for %s: %s", doi, pdf_url)
            return str(pdf_url)

    # Fallback: check all OA locations
    locations = data.get("oa_locations")
    if isinstance(locations, list):
        for loc in locations:
            if isinstance(loc, dict):
                pdf_url = loc.get("url_for_pdf")
                if pdf_url and isinstance(pdf_url, str):
                    logger.info(
                        "Unpaywall found alternate OA PDF for %s", doi,
                    )
                    return str(pdf_url)

    return None
