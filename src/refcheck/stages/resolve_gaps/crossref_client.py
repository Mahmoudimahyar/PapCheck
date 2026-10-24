"""Async client for CrossRef API."""

import logging
import os
from typing import Literal

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from refcheck.stages.resolve_gaps.markup import strip_jats, strip_markup
from refcheck.stages.resolve_gaps.title_guard import pick_best_hit

logger = logging.getLogger(__name__)

CROSSREF_BASE = "https://api.crossref.org"
_TIMEOUT = 15.0
_TITLE_CANDIDATES = 5
_NON_PAPER_TYPES = frozenset({"peer-review", "dataset", "component", "grant"})


class CrossRefResult:
    """Container for CrossRef lookup result."""

    def __init__(
        self,
        *,
        found: bool,
        title: str = "",
        authors: list[str] | None = None,
        year: int | None = None,
        doi: str = "",
        journal: str = "",
        url: str = "",
        abstract: str = "",
        status: Literal["found", "not_found", "api_error"] = "not_found",
    ) -> None:
        self.found = found
        self.title = title
        self.authors = authors or []
        self.year = year
        self.doi = doi
        self.journal = journal
        self.url = url
        self.abstract = abstract
        self.status = status


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5))
async def search_by_doi(
    doi: str,
    client: httpx.AsyncClient | None = None,
) -> CrossRefResult:
    """Look up a work by DOI."""
    email = os.environ.get("UNPAYWALL_EMAIL", "")
    headers: dict[str, str] = {}
    if email:
        headers["User-Agent"] = f"RefCheck/0.1 (mailto:{email})"

    should_close = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=_TIMEOUT)

    try:
        resp = await client.get(
            f"{CROSSREF_BASE}/works/{doi}", headers=headers
        )
        resp.raise_for_status()
        return _parse_crossref_work(resp.json())
    except httpx.TimeoutException:
        logger.warning("CrossRef timeout for DOI %s", doi)
        return CrossRefResult(found=False, status="api_error")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return CrossRefResult(found=False, status="not_found")
        return CrossRefResult(found=False, status="api_error")
    finally:
        if should_close:
            await client.aclose()


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5))
async def search_by_title(
    title: str,
    authors: list[str] | None = None,
    client: httpx.AsyncClient | None = None,
) -> CrossRefResult:
    """Search CrossRef by title (and optionally authors)."""
    email = os.environ.get("UNPAYWALL_EMAIL", "")
    headers: dict[str, str] = {}
    if email:
        headers["User-Agent"] = f"RefCheck/0.1 (mailto:{email})"

    query = title
    if authors:
        query += " " + " ".join(authors[:2])

    # Several candidates: derivative works (peer reviews, addenda, F1000
    # recommendations) often outrank the original for a title query.
    params = {"query.bibliographic": query, "rows": str(_TITLE_CANDIDATES)}
    should_close = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=_TIMEOUT)

    try:
        resp = await client.get(
            f"{CROSSREF_BASE}/works", params=params, headers=headers
        )
        resp.raise_for_status()
        data = resp.json()
        items = [
            it for it in data.get("message", {}).get("items", [])
            if isinstance(it, dict) and it.get("type") not in _NON_PAPER_TYPES
        ]
        candidates = [_parse_crossref_work({"message": it}) for it in items]
        best = pick_best_hit(title, [c for c in candidates if c.found], lambda c: c.title)
        return best or CrossRefResult(found=False, status="not_found")
    except httpx.TimeoutException:
        return CrossRefResult(found=False, status="api_error")
    except httpx.HTTPStatusError:
        return CrossRefResult(found=False, status="api_error")
    finally:
        if should_close:
            await client.aclose()


def _parse_crossref_work(data: dict[str, object]) -> CrossRefResult:
    """Parse CrossRef works API response."""
    msg = data.get("message", {})
    if not isinstance(msg, dict):
        return CrossRefResult(found=False)

    title_list = msg.get("title", [])
    title = title_list[0] if isinstance(title_list, list) and title_list else ""
    title = strip_markup(str(title))  # CrossRef titles may carry <p>, <i>, <sub>…
    doi = str(msg.get("DOI", ""))

    # Extract year from date-parts
    year: int | None = None
    issued = msg.get("issued", {})
    if isinstance(issued, dict):
        parts = issued.get("date-parts", [[]])
        if isinstance(parts, list) and parts:
            first = parts[0]
            if isinstance(first, list) and first:
                year = int(first[0]) if first[0] else None

    url = f"https://doi.org/{doi}" if doi else ""
    journal_list = msg.get("container-title", [])
    journal = journal_list[0] if isinstance(journal_list, list) and journal_list else ""

    return CrossRefResult(
        found=bool(title),
        title=str(title),
        year=year,
        doi=doi,
        journal=str(journal),
        url=url,
        abstract=strip_jats(str(msg.get("abstract", "") or "")),
        status="found" if title else "not_found",
    )
