"""Free-full-text hints from OpenAlex (metadata only: nothing is downloaded).

For a reference without a usable full text the resolve stage asks OpenAlex
(``/works/doi:<doi>``) whether a legal free copy exists, and stores its status,
URLs, licence and version on the reference (db/open_access.py) so the user can
fetch it. Lookups are cached, use a short timeout, send no contact e-mail, and
a failure leaves the reference unchanged.
"""

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

import httpx
from pydantic import BaseModel, Field

from refcheck.models.open_access import OpenAccessHint, with_access_hint
from refcheck.models.reference import Reference
from refcheck.stages.resolve_gaps.http_retry import send_with_backoff
from refcheck.stages.resolve_gaps.record_cache import load_record, store_record
from refcheck.utils.doi import dois_match, normalize_doi

logger = logging.getLogger(__name__)

OPENALEX_WORKS = "https://api.openalex.org/works/doi:"
_KIND = "openalex_oa_v1"
_TIMEOUT = 8.0
_CONCURRENCY = 5

FullTextGate = Callable[[Reference], bool]  # True: the reference lacks a usable full text


class CachedHint(BaseModel):
    """Cached OpenAlex answer for one DOI (found=False: OpenAlex has no such work)."""

    doi: str
    found: bool = False
    hint: OpenAccessHint = Field(default_factory=OpenAccessHint)


def lacks_full_text(ref: Reference) -> bool:
    """No PDF on disk, or the PDF is another paper (default gate).

    Supplements and scans need the match stage's PDF reader, which this stage
    may not import; the pipeline passes a fuller gate to ``add_access_hints``.
    """
    if ref.pdf_path is None or not Path(ref.pdf_path).is_file():
        return True
    return ref.identity_status == "mismatch"


def parse_openalex_work(data: object, doi: str) -> OpenAccessHint | None:
    """The hint of an OpenAlex work (None: not this DOI's work)."""
    if not isinstance(data, dict):
        return None
    work_doi = str(data.get("doi") or "")
    if work_doi and not dois_match(work_doi, doi):
        return None
    oa = data.get("open_access")
    best = data.get("best_oa_location")
    oa = oa if isinstance(oa, dict) else {}
    best = best if isinstance(best, dict) else {}
    is_oa = bool(oa.get("is_oa"))
    ids = data.get("ids")
    pmcid = str(ids.get("pmcid") or "") if isinstance(ids, dict) else ""
    return OpenAccessHint(
        oa_status=_text(oa.get("oa_status")),
        oa_url=(_text(oa.get("oa_url")) or _text(best.get("landing_page_url"))) if is_oa
        else None,
        oa_pdf_url=_text(best.get("pdf_url")) if is_oa else None,
        oa_license=_text(best.get("license")) if is_oa else None,
        oa_version=_text(best.get("version")) if is_oa else None,
        pmc_id=_pmc_id(pmcid),
    )


def _text(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _pmc_id(raw: str) -> str | None:
    """"https://www.ncbi.nlm.nih.gov/pmc/articles/7682336" -> "PMC7682336"."""
    digits = raw.rstrip("/").rsplit("/", 1)[-1].upper().removeprefix("PMC")
    return f"PMC{digits}" if digits.isdigit() else None


async def fetch_oa_hint(doi: str, client: httpx.AsyncClient) -> OpenAccessHint | None:
    """Cached OpenAlex hint for a DOI (None: unknown work or the API failed)."""
    key = normalize_doi(doi)
    if not key:
        return None
    cached = load_record(_KIND, key, CachedHint)
    if cached is not None:
        return cached.hint if cached.found else None
    try:
        url = f"{OPENALEX_WORKS}{quote(key, safe='/')}"
        resp = await send_with_backoff(lambda: client.get(url, timeout=_TIMEOUT), retries=1)
        if resp.status_code == 404:
            store_record(_KIND, key, CachedHint(doi=key))
            return None
        resp.raise_for_status()
        data: object = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.info("OpenAlex lookup failed for DOI %s: %s", key, exc)
        return None
    hint = parse_openalex_work(data, key)
    store_record(_KIND, key, CachedHint(doi=key, found=hint is not None,
                                        hint=hint or OpenAccessHint()))
    return hint


async def add_access_hints(
    refs: list[Reference], client: httpx.AsyncClient,
    gate: FullTextGate | None = None,
) -> list[Reference]:
    """References lacking a usable full text get their OpenAlex hint (never raises)."""
    needs = gate or lacks_full_text
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def _one(ref: Reference) -> Reference:
        try:
            if not ref.doi or not needs(ref):
                return ref
            async with sem:
                hint = await fetch_oa_hint(ref.doi, client)
        except Exception as exc:  # a hint is best-effort; never fail the stage
            logger.warning("Open-access hint failed for ref %d: %s", ref.id, exc)
            return ref
        return with_access_hint(ref, hint) if hint is not None else ref

    hinted = list(await asyncio.gather(*[_one(r) for r in refs]))
    found = sum(1 for old, new in zip(refs, hinted, strict=True) if new is not old)
    logger.info("Open-access hints: %d references looked up with a result", found)
    return hinted
