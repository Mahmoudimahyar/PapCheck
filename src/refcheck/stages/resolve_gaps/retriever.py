"""Download open-access PDFs from PMC and Unpaywall."""

import logging
import os
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

_TIMEOUT = 30.0
_PDF_MAGIC = b"%PDF"


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=2, max=10))
async def download_pmc_pdf(
    pmc_id: str,
    output_dir: Path,
    client: httpx.AsyncClient | None = None,
) -> Path | None:
    """Download a full-text PDF from PubMed Central."""
    url = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmc_id}/pdf/"
    return await _download_pdf(url, output_dir, f"pmc_{pmc_id}.pdf", client)


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=2, max=10))
async def download_unpaywall_pdf(
    doi: str,
    output_dir: Path,
    client: httpx.AsyncClient | None = None,
) -> Path | None:
    """Find and download an OA PDF via Unpaywall."""
    email = os.environ.get("UNPAYWALL_EMAIL", "")
    if not email:
        logger.warning("UNPAYWALL_EMAIL not set, skipping Unpaywall")
        return None

    api_url = f"https://api.unpaywall.org/v2/{doi}?email={email}"
    should_close = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=_TIMEOUT)

    try:
        resp = await client.get(api_url)
        resp.raise_for_status()
        data = resp.json()

        oa_location = data.get("best_oa_location")
        if not oa_location or not isinstance(oa_location, dict):
            return None

        pdf_url = oa_location.get("url_for_pdf") or oa_location.get("url")
        if not pdf_url:
            return None

        safe_doi = doi.replace("/", "_")
        return await _download_pdf(
            str(pdf_url), output_dir, f"unpaywall_{safe_doi}.pdf", client
        )
    except (httpx.TimeoutException, httpx.HTTPStatusError):
        logger.warning("Unpaywall lookup failed for DOI %s", doi)
        return None
    finally:
        if should_close:
            await client.aclose()


async def _download_pdf(
    url: str,
    output_dir: Path,
    filename: str,
    client: httpx.AsyncClient | None = None,
) -> Path | None:
    """Download a file and verify it's a valid PDF."""
    should_close = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True)

    try:
        resp = await client.get(url)
        resp.raise_for_status()

        content = resp.content
        if not content.startswith(_PDF_MAGIC):
            logger.warning("Downloaded file is not a PDF: %s", url)
            return None

        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / filename
        output_path.write_bytes(content)
        logger.info("Downloaded PDF: %s", output_path)
        return output_path
    except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
        logger.warning("PDF download failed from %s: %s", url, exc)
        return None
    finally:
        if should_close:
            await client.aclose()
