"""POST /references/{ref_id}/upload-pdf (in-memory DB, background task mocked)."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import fitz
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from refcheck.api.main import app
from refcheck.db import engine as engine_mod
from refcheck.db.converters import db_to_reference
from refcheck.db.deps import get_db
from refcheck.db.reference_repo import get_reference
from tests.unit.test_reverifier import _TITLE, _seed


@pytest.fixture
def engine() -> Iterator[object]:
    eng = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    previous = engine_mod._engine_instance
    engine_mod.set_engine(eng)
    yield eng
    engine_mod.set_engine(previous)


def _pdf_bytes(text: str) -> bytes:
    doc = fitz.open()
    doc.new_page().insert_textbox(fitz.Rect(40, 40, 560, 800), text, fontsize=9)
    data: bytes = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def client(engine: object) -> Iterator[TestClient]:
    def _db() -> Iterator[Session]:
        with Session(engine) as s:  # type: ignore[arg-type]
            yield s

    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _db
    yield TestClient(app)
    if previous is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous


class TestUploadEndpoint:
    def test_upload_saves_updates_and_schedules(
        self, client: TestClient, engine: object, tmp_path: Path,
    ) -> None:
        _seed(engine, tmp_path / "pdfs")
        body = _pdf_bytes(f"{_TITLE}\nJohn Smith\n2020\n" + "Cartilage text. " * 40)
        task = MagicMock()
        with patch("refcheck.api.routes.references.reverify_reference", task):
            resp = client.post(
                "/api/sessions/s1/references/10/upload-pdf",
                files={"pdf": ("paper.pdf", body, "application/pdf")},
            )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["claims_to_reverify"] == [1]
        assert data["reverification_started"] is True
        assert data["identity_status"] == "verified"
        saved = tmp_path / "pdfs" / "ref_10_user_upload.pdf"
        assert saved.read_bytes() == body
        with Session(engine) as db:  # type: ignore[arg-type]
            row = get_reference(db, "s1", 10)
            assert row is not None
            ref = db_to_reference(row)
        assert ref.pdf_source == "user_upload" and ref.source_status == "found"
        assert ref.pdf_path == saved
        args = task.call_args.args
        assert args[:3] == ("s1", 10, [1])
        assert args[3]["identity_status"] == "verified"

    def test_rejects_non_pdf_content(
        self, client: TestClient, engine: object, tmp_path: Path,
    ) -> None:
        _seed(engine, tmp_path)
        resp = client.post(
            "/api/sessions/s1/references/10/upload-pdf",
            files={"pdf": ("paper.pdf", b"hello", "application/pdf")},
        )
        assert resp.status_code == 400

    def test_unknown_reference(self, client: TestClient, engine: object, tmp_path: Path) -> None:
        _seed(engine, tmp_path)
        resp = client.post(
            "/api/sessions/s1/references/99/upload-pdf",
            files={"pdf": ("paper.pdf", _pdf_bytes("x"), "application/pdf")},
        )
        assert resp.status_code == 404
