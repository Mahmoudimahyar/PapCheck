"""Local PDF library indexes (V5.8, G3): run-store keys, library.db rows, read-only reads."""

import hashlib
import sqlite3
from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine

from refcheck.library.models import LibraryPaper
from refcheck.library.store import (
    db_paths,
    keyed_paths,
    library_db_path,
    library_pdfs,
    pdf_key,
    shared_library_dir,
)
from tests.unit.rematch_fakes import ref


def _key(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4 synthetic")
    return path


def test_locations_come_from_the_environment(monkeypatch: pytest.MonkeyPatch,
                                             tmp_path: Path) -> None:
    monkeypatch.setenv("REFCHECK_SHARED_LIBRARY_DIR", str(tmp_path / "lib"))
    monkeypatch.setenv("REFCHECK_LIBRARY_DB", str(tmp_path / "lib.db"))
    assert shared_library_dir() == tmp_path / "lib"
    assert library_db_path() == tmp_path / "lib.db"
    assert not (tmp_path / "lib").exists()  # reading the location creates nothing


def test_pdf_key_uses_the_doi_then_the_title() -> None:
    assert pdf_key(ref(1, doi="10.5555/Synth.1")) == f"doi_{_key('10.5555/Synth.1')}"
    assert pdf_key(ref(1, doi=None, title="A title")) == f"title_{_key('A title')}"


def test_keyed_paths_find_the_doi_in_any_case_and_the_title(tmp_path: Path) -> None:
    lower = _touch(tmp_path / f"doi_{_key('10.5555/synth.1')}.pdf")
    titled = _touch(tmp_path / f"title_{_key('Some title')}.pdf")
    found = keyed_paths(ref(1, doi="10.5555/SYNTH.1", title="Some title"), tmp_path)
    assert found == [lower, titled]
    assert keyed_paths(ref(2, doi="10.5555/other", title="Other"), tmp_path) == []


def _library_db(path: Path, papers: list[LibraryPaper]) -> Path:
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    SQLModel.metadata.create_all(engine, tables=[LibraryPaper.__table__])  # type: ignore[attr-defined]
    with Session(engine) as db:
        for paper in papers:
            db.add(paper)
        db.commit()
    engine.dispose()
    return path


def test_db_rows_match_by_doi_or_fuzzy_title(tmp_path: Path) -> None:
    by_doi = _touch(tmp_path / "pdfs" / "a.pdf")
    by_title = _touch(tmp_path / "pdfs" / "b.pdf")
    db = _library_db(tmp_path / "library.db", [
        LibraryPaper(doi="10.5555/SYNTH.9", title="Unrelated", pdf_path=str(by_doi)),
        LibraryPaper(title="Porous capsules protect islets in mice", pdf_path=str(by_title)),
        LibraryPaper(doi="10.5555/gone", title="Missing file", pdf_path=str(tmp_path / "x.pdf")),
    ])
    assert db_paths(ref(1, doi="10.5555/synth.9", title="Nothing alike"), db) == [by_doi]
    assert db_paths(ref(2, doi=None, title="Porous capsules protect islets in mice."), db) \
        == [by_title]
    assert db_paths(ref(3, doi="10.5555/gone", title="Missing file"), db) == []


def test_library_pdfs_lists_both_indexes_once(tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    store = _touch(lib / "doi_x.pdf")
    row = _touch(lib / "pdfs" / "upload.pdf")
    db = _library_db(tmp_path / "library.db", [
        LibraryPaper(title="t", pdf_path=str(row)), LibraryPaper(title="u", pdf_path=str(store))])
    assert library_pdfs(lib, db) == [store, row]


def test_missing_library_and_db_read_as_empty(tmp_path: Path) -> None:
    lib = tmp_path / "absent"
    assert library_pdfs(lib, tmp_path / "absent.db") == []
    assert db_paths(ref(1), tmp_path / "absent.db") == []
    assert not lib.exists() and not (tmp_path / "absent.db").exists()


def test_db_without_the_table_reads_as_empty(tmp_path: Path) -> None:
    db = tmp_path / "other.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE sessions (id TEXT)")
    conn.commit()
    conn.close()
    assert db_paths(ref(1), db) == []
