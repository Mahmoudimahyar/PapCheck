"""Upload-PDF endpoint + background re-verification (DB in memory, LLM mocked)."""

import sys
import types
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from refcheck.db import engine as engine_mod
from refcheck.db.converters import (
    claim_to_db,
    db_to_verification,
    reference_to_db,
    verification_to_db,
)
from refcheck.db.models import SessionDB
from refcheck.db.verification_repo import get_all_verifications
from refcheck.models.claim import Claim
from refcheck.models.reference import Reference
from refcheck.models.verification import VerificationResult
from refcheck.services.reverifier import (
    find_claims_to_reverify,
    merge_verifications,
    reverify_reference,
    save_uploaded_pdf,
)

_TITLE = "Injectable hydrogels for cartilage repair in osteoarthritic knees"


def _v(
    claim_id: int, ref_id: int, verdict: str = "cannot_verify", **kw: object,
) -> VerificationResult:
    return VerificationResult.model_validate(
        {"claim_id": claim_id, "reference_id": ref_id, "verdict": verdict, **kw},
    )


def _claim(cid: int, refs: list[int]) -> Claim:
    return Claim(id=cid, extracted_claim=f"claim {cid}", reference_ids=refs)


class TestSelection:
    def test_all_claims_citing_reference_except_user_overrides(self) -> None:
        claims = [_claim(1, [10]), _claim(2, [10]), _claim(3, [20]), _claim(4, [10, 20])]
        results = [
            _v(1, 10, "supported"),
            _v(2, 10, "not_supported", user_override=True),
            _v(4, 10, "cannot_verify", cannot_verify_reason="no_pdf_paywalled"),
        ]
        assert find_claims_to_reverify(claims, results, 10) == [1, 4]

    def test_no_claims(self) -> None:
        assert find_claims_to_reverify([], [], 10) == []

    def test_merge_replaces_only_reverified_pairs(self) -> None:
        old = [_v(1, 10, "cannot_verify"), _v(1, 20, "supported"), _v(2, 10, "supported")]
        new = [_v(1, 10, "contradicted")]
        merged = merge_verifications(old, new)
        assert len(merged) == 3
        assert {(m.claim_id, m.reference_id, m.verdict) for m in merged} == {
            (1, 10, "contradicted"), (1, 20, "supported"), (2, 10, "supported"),
        }

    def test_save_uploaded_pdf(self, tmp_path: Path) -> None:
        path = save_uploaded_pdf(tmp_path / "pdfs", 7, b"%PDF-1.4 data")
        assert path.name == "ref_7_user_upload.pdf"
        assert path.read_bytes() == b"%PDF-1.4 data"


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


def _seed(eng: object, pdf_dir: Path) -> None:
    with Session(eng) as db:  # type: ignore[arg-type]
        db.add(SessionDB(id="s1", manuscript_filename="m.docx", pdf_dir=str(pdf_dir)))
        db.add(reference_to_db(Reference(id=10, title=_TITLE, authors=["J. Smith"]), "s1"))
        db.add(reference_to_db(Reference(id=20, title="Other"), "s1"))
        for c in (_claim(1, [10]), _claim(2, [10]), _claim(3, [20])):
            db.add(claim_to_db(c, "s1"))
        for v in (
            _v(1, 10, cannot_verify_reason="no_pdf_paywalled"),
            _v(2, 10, "supported", user_override=True),
            _v(3, 20, "supported"),
        ):
            db.add(verification_to_db(v, "s1"))
        db.commit()


def _install_verifier(monkeypatch: pytest.MonkeyPatch, calls: list[object]) -> None:
    async def _verify(claims: list[Claim], refs: list[Reference]) -> list[VerificationResult]:
        calls.append((claims, refs))
        return [_v(c.id, refs[0].id, "supported", reasoning="re-verified") for c in claims]

    module = types.ModuleType("refcheck.stages.verify_claims")
    module.verify_claims = _verify  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "refcheck.stages.verify_claims", module)


@pytest.mark.asyncio
async def test_reverify_reference_persists_merged_results(
    engine: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed(engine, tmp_path)
    calls: list[object] = []
    _install_verifier(monkeypatch, calls)
    updates = {"pdf_path": tmp_path / "x.pdf", "identity_status": "mismatch"}
    out = await reverify_reference("s1", 10, [1], updates)
    assert [r.claim_id for r in out] == [1]
    claims, refs = calls[0]  # type: ignore[misc]
    assert refs[0].identity_status == "mismatch"  # in-memory updates applied
    assert claims[0].reference_ids == [10]
    with Session(engine) as db:  # type: ignore[arg-type]
        stored = {
            (v.claim_id, v.reference_id): v
            for v in map(db_to_verification, get_all_verifications(db, "s1"))
        }
    assert stored[(1, 10)].reasoning == "re-verified"
    assert stored[(2, 10)].user_override is True
    assert stored[(3, 20)].verdict == "supported"


@pytest.mark.asyncio
async def test_reverify_failure_is_logged_not_raised(
    engine: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed(engine, tmp_path)

    async def _boom(*args: object) -> list[VerificationResult]:
        raise RuntimeError("all models down")

    module = types.ModuleType("refcheck.stages.verify_claims")
    module.verify_claims = _boom  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "refcheck.stages.verify_claims", module)
    with patch("refcheck.services.verify_runner.record_session_error") as rec:
        assert await reverify_reference("s1", 10, [1]) == []
    assert "all models down" in rec.call_args.args[1]
