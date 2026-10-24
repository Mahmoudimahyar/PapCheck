"""Pick a PDF of the user's local library for a reference without a usable PDF (V5.8, G3).

Before a reference whose PDF is another paper, a supplement or a scan (or which has
no PDF) falls back to its abstract, the local PDF library is searched with the
re-match evidence rules of the upload pass (rematch_evidence): the PDF prints the
reference DOI as its own (corroborated), or the whole title aligns with page 1 with
the first author and the year; the identity gate (injected: stages do not import
each other) must not report a mismatch, and must report "verified" for a title-only
link. A file the library stored under this reference's own DOI / title key is
accepted on those rules or on a "verified" identity (key + title/author check), never
on "unverified": the library holds copies of earlier uploads, wrong ones included.
Supplements, scans, a copy of the reference's own rejected PDF and ambiguous picks
(two different papers qualify, or another reference of the manuscript claims the
PDF at least as strongly) are never linked.
"""

import hashlib
import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from refcheck.models.reference import Reference
from refcheck.stages.match_pdfs.rematch_evidence import RematchMethod, assess, decide
from refcheck.stages.match_pdfs.rematch_models import IdentityGate, PdfReader, RejectReason
from refcheck.stages.match_pdfs.rematch_select import Candidate, contested, pick_candidate

logger = logging.getLogger(__name__)

LibraryMethod = Literal["library_doi", "library_title", "library_key"]
_METHODS: dict[RematchMethod, LibraryMethod] = {
    "rematch_doi": "library_doi", "rematch_title": "library_title"}


class LibraryMatch(BaseModel):
    """A library PDF chosen for a reference, and why the reference needed one."""

    reference_id: int
    pdf_path: str
    method: LibraryMethod
    reason: RejectReason


def match_in_library(
    ref: Reference, keyed: list[Path], pool: list[Path], references: list[Reference],
    reader: PdfReader, identity: IdentityGate, reason: RejectReason,
) -> LibraryMatch | None:
    """The one library PDF that stands for `ref` (module doc), or None."""
    own = _own_digest(ref)
    keyed_set = {str(p) for p in keyed}
    paths = list(dict.fromkeys([*keyed, *pool]))
    found: list[tuple[Candidate, LibraryMethod]] = []
    for path in paths:
        qualified = _qualify(ref, path, str(path) in keyed_set, reader, identity, own)
        profile = reader.profile(path)
        if qualified is None or profile is None:
            continue
        evidence = assess(ref, profile)
        # library_key ranks like a title link when copies are compared (rematch_select)
        route: RematchMethod = "rematch_doi" if qualified == "library_doi" else "rematch_title"
        found.append((Candidate(profile=profile, evidence=evidence, method=route), qualified))
    chosen = pick_candidate(ref, [c for c, _ in found])
    if chosen is None or contested(ref, chosen, references):
        return None
    method = next(m for c, m in found if c.profile.path == chosen.profile.path)
    logger.info("Library: ref %d -> %s (%s; %s)", ref.id, chosen.profile.name, method, reason)
    return LibraryMatch(reference_id=ref.id, pdf_path=chosen.profile.path, method=method,
                        reason=reason)


def _qualify(
    ref: Reference, path: Path, keyed: bool, reader: PdfReader, identity: IdentityGate,
    own: tuple[int, str] | None,
) -> LibraryMethod | None:
    """How `path` may stand for `ref` (None: it may not)."""
    profile = reader.profile(path)
    if profile is None or not profile.usable or _same_file(path, own):
        return None
    route = decide(ref, assess(ref, profile))
    if route is None and not keyed:
        return None  # the cheap evidence check spares the identity read of every file
    if reader.supplement(path):
        return None
    status = identity(ref, path)
    if route is not None and (status == "verified"
                              or (route == "rematch_doi" and status != "mismatch")):
        return _METHODS[route]
    return "library_key" if keyed and status == "verified" else None


def _own_digest(ref: Reference) -> tuple[int, str] | None:
    """(size, sha256) of the reference's current (rejected) PDF, if any."""
    if ref.pdf_path is None or not Path(ref.pdf_path).is_file():
        return None
    path = Path(ref.pdf_path)
    return path.stat().st_size, _sha256(path)


def _same_file(path: Path, own: tuple[int, str] | None) -> bool:
    """A library copy of the reference's own rejected PDF (same bytes)."""
    if own is None:
        return False
    try:
        return path.stat().st_size == own[0] and _sha256(path) == own[1]
    except OSError:
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()
