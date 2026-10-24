"""Where the local PDF library lives, and which of its files may hold a reference.

Two indexes share one folder (default ~/.refcheck/library):
- the run store: every usable PDF of a run is copied in under a key of its
  reference ("doi_<sha256[:16]>.pdf" of the DOI, else "title_<...>.pdf");
- library.db rows (PDFs added on the Library page), with DOI and title.
Read paths never create anything (an offline audit opens the library read-only).
Locations: REFCHECK_SHARED_LIBRARY_DIR, REFCHECK_LIBRARY_DB.
"""

import hashlib
import logging
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from rapidfuzz import fuzz

from refcheck.models.reference import Reference
from refcheck.utils.doi import normalize_doi

logger = logging.getLogger(__name__)

_TITLE_RATIO = 92.0  # library.db title match (same threshold as repository.find_paper)


def shared_library_dir() -> Path:
    """The run store's folder (not created here)."""
    default = Path.home() / ".refcheck" / "library"
    return Path(os.getenv("REFCHECK_SHARED_LIBRARY_DIR", "") or default)


def library_db_path() -> Path:
    """library.db of the Library page (not created here)."""
    default = Path.home() / ".refcheck" / "library.db"
    return Path(os.getenv("REFCHECK_LIBRARY_DB", "") or default)


def pdf_key(ref: Reference) -> str:
    """Run-store key of a reference: its DOI as written, else its title, else its id."""
    if ref.doi:
        return f"doi_{_digest(ref.doi)}"
    if ref.title:
        return f"title_{_digest(ref.title)}"
    return f"ref_{ref.id}"


def keyed_paths(ref: Reference, lib_dir: Path) -> list[Path]:
    """Existing run-store files stored under this reference's DOI (any case) or title."""
    keys: list[str] = []
    if ref.doi:
        keys += [f"doi_{_digest(ref.doi)}", f"doi_{_digest(normalize_doi(ref.doi))}"]
    if ref.title:
        keys.append(f"title_{_digest(ref.title)}")
    paths = [lib_dir / f"{key}.pdf" for key in dict.fromkeys(keys)]
    return [p for p in paths if p.is_file()]


def library_pdfs(lib_dir: Path, db_path: Path) -> list[Path]:
    """Every PDF of both indexes (run store files, then library.db files), once."""
    files = sorted(lib_dir.glob("*.pdf"), key=lambda p: p.name.lower()) \
        if lib_dir.is_dir() else []
    rows = [Path(path) for _, _, path in _db_rows(db_path)]
    return list(dict.fromkeys([*files, *(p for p in rows if p.is_file())]))


def db_paths(ref: Reference, db_path: Path) -> list[Path]:
    """library.db files recorded with this reference's DOI or (fuzzy) title."""
    doi = normalize_doi(ref.doi or "")
    title = (ref.title or "").lower()
    found: list[Path] = []
    for row_doi, row_title, path in _db_rows(db_path):
        same_doi = bool(doi) and normalize_doi(row_doi or "") == doi
        same_title = bool(title) and fuzz.token_sort_ratio(title, row_title.lower()) > _TITLE_RATIO
        if (same_doi or same_title) and Path(path).is_file():
            found.append(Path(path))
    return list(dict.fromkeys(found))


def _db_rows(db_path: Path) -> list[tuple[str | None, str, str]]:
    """(doi, title, pdf_path) of every library.db paper, read-only ([] without a DB)."""
    if not db_path.is_file():
        return []
    try:
        with closing(sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)) as conn:
            rows = conn.execute(
                "SELECT doi, title, pdf_path FROM library_papers WHERE pdf_path != ''",
            ).fetchall()
    except sqlite3.Error as exc:  # no table yet, locked or corrupt: the run store still works
        logger.info("Library DB not readable (%s): %s", db_path, exc)
        return []
    return [(str(d) if d else None, str(t or ""), str(p)) for d, t, p in rows]


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]
