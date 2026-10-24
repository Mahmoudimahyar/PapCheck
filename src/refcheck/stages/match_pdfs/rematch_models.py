"""Data of the match-stage re-match pass (what was linked, and why it was tried)."""

from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from refcheck.models.matching import MatchResult
from refcheck.models.reference import Reference
from refcheck.stages.match_pdfs.pdf_profile import PdfProfile, read_pdf_profile
from refcheck.stages.match_pdfs.rematch_evidence import RematchMethod
from refcheck.stages.match_pdfs.supplement_detector import is_supplement_pdf

IdentityGate = Callable[[Reference, Path], str]  # -> "verified" | "unverified" | "mismatch"
RejectReason = Literal["no_pdf", "supplement", "no_text", "scanned", "identity_mismatch"]

_CACHED_FILES = 1024  # library + uploads of a run; a profile holds two pages of text


class RematchRecord(BaseModel):
    """One reference linked by the re-match pass."""

    reference_id: int
    pdf_path: str
    method: RematchMethod
    reason: RejectReason  # why the first pass left the reference without a usable PDF
    replaced_pdf: str | None = None


class RematchOutcome(BaseModel):
    """Match results after the re-match pass, and what it changed."""

    results: list[MatchResult] = Field(default_factory=list)
    records: list[RematchRecord] = Field(default_factory=list)
    rejected: dict[int, RejectReason] = Field(default_factory=dict)  # every re-match attempt


class PdfReader:
    """Reads every PDF at most once per file version (profile and supplement check).

    The cache is process-wide: the match stage and the library pass of the resolve
    stage read the same uploads, and the shared library is read once per process.
    """

    def profile(self, path: Path) -> PdfProfile | None:
        version = _file_version(path)
        return _profile(str(path), *version) if version else None

    def supplement(self, path: Path) -> bool:
        version = _file_version(path)
        return _supplement(str(path), *version) if version else is_supplement_pdf(path)


def _file_version(path: Path) -> tuple[int, int] | None:
    """(mtime_ns, size) of the file; None when it cannot be read."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


@lru_cache(maxsize=_CACHED_FILES)
def _profile(path: str, mtime_ns: int, size: int) -> PdfProfile | None:
    del mtime_ns, size  # cache key only
    return read_pdf_profile(Path(path))


@lru_cache(maxsize=_CACHED_FILES)
def _supplement(path: str, mtime_ns: int, size: int) -> bool:
    del mtime_ns, size  # cache key only
    return is_supplement_pdf(Path(path))
