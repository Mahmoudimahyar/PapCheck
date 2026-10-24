"""Download an open-access copy of a reference into a staging file (opt-in, oa_settings).

Each candidate URL (oa_sources) is downloaded with checks before anything is kept:
HTTP 200 from an http(s) URL, a PDF (or generic binary) content type — a publisher's
HTML landing page is refused —, a declared and an actual size under the cap, and the
"%PDF-" signature in the first 1,024 bytes. A staged file is then checked by the
caller's `accept` (the same identity / supplement / scan checks as an upload) and
deleted when refused. At most three candidates are downloaded per reference.
"""

import hashlib
import logging
from collections.abc import Callable
from pathlib import Path

import httpx
from pydantic import BaseModel

from refcheck.library.oa_settings import OaSettings, under_pytest
from refcheck.library.oa_sources import OaLink, OaSource, oa_links
from refcheck.models.reference import Reference

logger = logging.getLogger(__name__)

_PDF_TYPES = frozenset({"application/pdf", "application/x-pdf", "application/octet-stream",
                        "binary/octet-stream", ""})
_MAGIC = b"%PDF-"
_MAGIC_WINDOW = 1024
_MAX_CANDIDATES = 3
_USER_AGENT = "RefCheck-OA-fetch/1.0"


class OaDownload(BaseModel):
    """A downloaded candidate (path set) or why it was refused."""

    path: Path | None = None
    reason: str = "ok"


class OaFetched(BaseModel):
    """A staged open-access PDF that passed the caller's checks."""

    path: Path
    source: OaSource
    url: str


def open_client(settings: OaSettings) -> httpx.Client:
    """HTTP client of a live fetch (redirects followed, bounded)."""
    return httpx.Client(timeout=settings.timeout_s, follow_redirects=True, max_redirects=5,
                        headers={"User-Agent": _USER_AGENT})


def fetch_open_access(
    ref: Reference, staging_dir: Path, accept: Callable[[Path], bool],
    settings: OaSettings, client: httpx.Client | None = None,
) -> OaFetched | None:
    """The first open-access PDF of `ref` that `accept` keeps (staged; caller stores it).

    Nothing is fetched unless the setting is on; under pytest only an injected
    (mocked) client is used.
    """
    if not settings.enabled:
        return None
    if client is None and under_pytest():
        logger.warning("OA fetch: live downloads never run under pytest")
        return None
    own = client or open_client(settings)
    try:
        return _fetch(ref, staging_dir, accept, settings, own)
    finally:
        if client is None:
            own.close()


def _fetch(
    ref: Reference, staging_dir: Path, accept: Callable[[Path], bool],
    settings: OaSettings, client: httpx.Client,
) -> OaFetched | None:
    for link in oa_links(client, ref, settings.contact_email)[:_MAX_CANDIDATES]:
        dest = staging_dir / f"oa_{ref.id}_{_short(link.url)}.pdf"
        download = download_pdf(client, link.url, dest, settings.max_bytes)
        if download.path is None:
            logger.info("OA fetch: ref %d %s refused (%s)", ref.id, link.source, download.reason)
            continue
        if accept(download.path):
            return OaFetched(path=download.path, source=link.source, url=link.url)
        logger.info("OA fetch: ref %d %s PDF failed the identity checks", ref.id, link.source)
        download.path.unlink(missing_ok=True)
    return None


def download_pdf(client: httpx.Client, url: str, dest: Path, max_bytes: int) -> OaDownload:
    """Download `url` to `dest` when it is a PDF under `max_bytes` (module doc)."""
    try:
        with client.stream("GET", url) as response:
            refused = _refused(response, max_bytes)
            if refused:
                return OaDownload(reason=refused)
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > max_bytes:
                    return OaDownload(reason="too_large")
    except httpx.HTTPError as exc:
        return OaDownload(reason=f"http_error:{type(exc).__name__}")
    if _MAGIC not in bytes(body[:_MAGIC_WINDOW]):
        return OaDownload(reason="not_a_pdf")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(bytes(body))
    return OaDownload(path=dest)


def _refused(response: httpx.Response, max_bytes: int) -> str:
    """Why the response is not worth reading ("" when it is)."""
    if response.status_code != httpx.codes.OK:
        return f"http_{response.status_code}"
    if response.url.scheme not in ("http", "https"):
        return "scheme"
    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type not in _PDF_TYPES:
        return f"type:{content_type}"
    declared = response.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > max_bytes:
        return "too_large"
    return ""


def _short(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:10]


__all__ = ["OaDownload", "OaFetched", "OaLink", "download_pdf", "fetch_open_access",
           "open_client"]
