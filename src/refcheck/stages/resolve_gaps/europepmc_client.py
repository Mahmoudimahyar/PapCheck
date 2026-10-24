"""Europe PMC abstracts by DOI (or PMID), cached; the last-but-one abstract source.

Europe PMC often has the abstract when PubMed/Semantic Scholar/CrossRef do not
(older LWW and Elsevier papers) or have only a stub. The REST search returns
``abstractText`` as HTML (``<h4>`` section headings, ``<i>``/``<sup>``), which is
turned into plain text with "Heading: " prefixes. A hit counts only when its DOI
(or PMID) is the one asked for. No contact e-mail is sent.
"""

import asyncio
import logging
import re

import httpx
from pydantic import BaseModel

from refcheck.stages.resolve_gaps.http_retry import send_with_backoff
from refcheck.stages.resolve_gaps.markup import strip_markup
from refcheck.stages.resolve_gaps.record_cache import load_record, store_record
from refcheck.utils.doi import dois_match, normalize_doi

logger = logging.getLogger(__name__)

EUROPEPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_KIND = "europepmc_abstract_v1"
_TIMEOUT = 10.0
_CONCURRENCY = 6
_HEADING_RE = re.compile(r"<h\d\b[^>]*>(.*?)</h\d>", re.DOTALL | re.IGNORECASE)


class EuropePmcAbstract(BaseModel):
    """Cached Europe PMC abstract for one key ("" = Europe PMC has none)."""

    key: str
    abstract: str = ""


def europepmc_key(doi: str | None, pmid: str | None) -> str:
    """Lookup key of a reference: "doi:<normalized>" or "pmid:<digits>" ("" = none)."""
    if doi and normalize_doi(doi):
        return f"doi:{normalize_doi(doi)}"
    digits = "".join(ch for ch in (pmid or "") if ch.isdigit())
    return f"pmid:{digits}" if digits else ""


def html_abstract_to_text(raw: str) -> str:
    """Plain text of an Europe PMC ``abstractText`` (headings become "Title: ")."""

    def _heading(match: re.Match[str]) -> str:
        title = strip_markup(match.group(1)).rstrip(":")
        if not title or title.lower() == "abstract":
            return " "
        return f" {title}: "

    return strip_markup(_HEADING_RE.sub(_heading, raw or ""))


def pick_abstract(data: object, key: str) -> str:
    """Abstract of the result matching `key` in a search response ("" = none)."""
    if not isinstance(data, dict):
        return ""
    result_list = data.get("resultList")
    results = result_list.get("result") if isinstance(result_list, dict) else None
    if not isinstance(results, list):
        return ""
    kind, _, value = key.partition(":")
    for item in results:
        if not isinstance(item, dict):
            continue
        same = dois_match(str(item.get("doi") or ""), value) if kind == "doi" \
            else str(item.get("pmid") or "") == value
        if same:
            return html_abstract_to_text(str(item.get("abstractText") or ""))
    return ""


async def fetch_europepmc_abstracts(
    keys: list[str], client: httpx.AsyncClient,
) -> dict[str, str]:
    """Abstracts by `europepmc_key` (misses cached as ""; API errors omitted)."""
    abstracts: dict[str, str] = {}
    missing: list[str] = []
    for key in dict.fromkeys(k for k in keys if k):
        cached = load_record(_KIND, key, EuropePmcAbstract)
        if cached is not None:
            abstracts[key] = cached.abstract
        else:
            missing.append(key)

    sem = asyncio.Semaphore(_CONCURRENCY)

    async def _one(key: str) -> None:
        async with sem:
            text = await _search(key, client)
        if text is not None:
            store_record(_KIND, key, EuropePmcAbstract(key=key, abstract=text))
            abstracts[key] = text

    await asyncio.gather(*[_one(k) for k in missing])
    return abstracts


async def _search(key: str, client: httpx.AsyncClient) -> str | None:
    """One search request; None when the API failed (not cached, retried next run)."""
    kind, _, value = key.partition(":")
    query = f'DOI:"{value}"' if kind == "doi" else f"EXT_ID:{value} AND SRC:MED"
    params = {"query": query, "resultType": "core", "format": "json", "pageSize": "5"}
    try:
        resp = await send_with_backoff(
            lambda: client.get(EUROPEPMC_SEARCH, params=params, timeout=_TIMEOUT),
        )
        resp.raise_for_status()
        data: object = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Europe PMC lookup failed for %s: %s", key, exc)
        return None
    return pick_abstract(data, key)
