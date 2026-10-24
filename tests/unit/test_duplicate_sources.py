"""A duplicated reference entry is verified with its original's source (no network).

Regression (integration review): once "Wang et al., 2024b" mapped to its own
duplicate entry (year-suffix fix), that entry had no PDF (matching gives the
file to the first entry only), so its claims fell back to the abstract or to
no source at all although the paper's full text was attached.
"""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from refcheck.stages.verify_claims import verify_claims
from refcheck.stages.verify_claims.duplicate_sources import inherit_duplicate_sources
from refcheck.stages.verify_claims.retrieval_embed import clear_embedding_cache
from tests.unit.test_verifier import Fakes, _pdf
from tests.unit.verify_fakes import ABSTRACT, make_claim, make_ref

_V = "refcheck.stages.verify_claims"


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> Iterator[Fakes]:
    for name in ("REFCHECK_SCREEN_ENABLED", "REFCHECK_PRIVACY_PROFILE",
                 "REFCHECK_SCREEN_T_ACCEPT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("REFCHECK_SCREEN_CALIBRATION", "does-not-exist.json")
    clear_embedding_cache()
    f = Fakes()
    with patch(f"{_V}.verifier.preflight", f.preflight), patch(f"{_V}.screen.decide", f.decide), \
            patch(f"{_V}.layers.call_llm_raw", f.llm), \
            patch(f"{_V}.retrieval_embed.embed_texts", AsyncMock(side_effect=RuntimeError("x"))):
        yield f


def test_duplicate_without_pdf_inherits_pdf_identity_and_abstract(tmp_path: Path) -> None:
    pdf = tmp_path / "a.pdf"
    original = make_ref(1, pdf_path=pdf, identity_status="verified",
                        abstract_text=ABSTRACT, abstract_source="pubmed")
    duplicate = make_ref(2, duplicate_of=1)
    out = {r.id: r for r in inherit_duplicate_sources([original, duplicate])}
    assert out[2].pdf_path == pdf and out[2].identity_status == "verified"
    assert out[2].abstract_text == ABSTRACT and out[2].abstract_source == "pubmed"
    assert out[2].duplicate_of == 1 and out[1] == original


def test_duplicate_keeps_its_own_pdf_and_mismatch_is_inherited(tmp_path: Path) -> None:
    own = make_ref(2, duplicate_of=1, pdf_path=tmp_path / "own.pdf")
    original = make_ref(1, pdf_path=tmp_path / "a.pdf", identity_status="mismatch")
    assert inherit_duplicate_sources([original, own])[1].pdf_path == tmp_path / "own.pdf"
    bare = make_ref(3, duplicate_of=1)
    assert inherit_duplicate_sources([original, bare])[1].identity_status == "mismatch"


def test_non_duplicates_and_dangling_links_are_unchanged() -> None:
    refs = [make_ref(1), make_ref(2, duplicate_of=99), make_ref(3, duplicate_of=3)]
    assert inherit_duplicate_sources(refs) == refs


async def test_claim_on_duplicate_entry_is_verified_on_the_full_text(
    fakes: Fakes, tmp_path: Path,
) -> None:
    original = make_ref(1, pdf_path=_pdf(tmp_path), identity_status="verified")
    duplicate = make_ref(2, duplicate_of=1)
    claim = make_claim().model_copy(update={"reference_ids": [2]})
    result = (await verify_claims([claim], [original, duplicate]))[0]
    assert result.reference_id == 2
    assert result.source_coverage == "full_text" and result.verdict == "supported"
