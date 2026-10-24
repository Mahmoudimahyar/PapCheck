"""Source resolution for verification: abstract fallback, no source, unusable PDFs (V5)."""

from pathlib import Path

from refcheck.models.reference import Reference
from refcheck.stages.verify_claims.verifier_helpers import resolve_source
from tests.unit.verify_fakes import ABSTRACT

# An abstract that may stand in for an unusable PDF must be long enough to judge (>= 300 chars).
LONG_ABSTRACT = ABSTRACT + " Treated mice kept their body weight throughout the whole study period."


def _make_ref(pdf_path: Path | None = None, abstract: str | None = None,
              **fields: object) -> Reference:
    return Reference.model_validate({
        "id": 1, "raw_text": "Smith (2020). Title. Nature.", "title": "Test Paper",
        "pdf_path": pdf_path, "abstract_text": abstract,
        "abstract_source": "pubmed" if abstract else None, **fields,
    })


async def test_abstract_only_coverage_when_no_pdf() -> None:
    src = await resolve_source(_make_ref(abstract=ABSTRACT))
    assert src.coverage == "abstract_only" and src.doc is not None
    assert src.doc.chunks[0].kind == "abstract" and src.cannot_verify_reason is None


async def test_no_source_when_no_pdf_no_abstract() -> None:
    src = await resolve_source(_make_ref())
    assert src.doc is None and src.coverage == "no_source"
    assert src.cannot_verify_reason == "no_pdf_not_found"
    paywalled = await resolve_source(_make_ref(doi="10.1/abc"))
    assert paywalled.cannot_verify_reason == "no_pdf_paywalled"


async def test_unreadable_pdf_falls_back_to_abstract(tmp_path: Path) -> None:
    pdf_file = tmp_path / "paper.pdf"
    pdf_file.write_text("not a real PDF")
    src = await resolve_source(_make_ref(pdf_path=pdf_file, abstract=LONG_ABSTRACT))
    assert src.coverage == "abstract_only" and src.doc is not None


async def test_unreadable_pdf_without_abstract_is_low_quality_not_no_source(
    tmp_path: Path,
) -> None:
    pdf_file = tmp_path / "paper.pdf"
    pdf_file.write_text("not a real PDF")
    src = await resolve_source(_make_ref(pdf_path=pdf_file))
    assert src.doc is None and src.coverage == "full_text"
    assert src.cannot_verify_reason == "pdf_scanned"


async def test_identity_mismatch_uses_abstract_or_reports_mismatch(tmp_path: Path) -> None:
    pdf_file = tmp_path / "paper.pdf"
    pdf_file.write_text("whatever")
    with_abstract = await resolve_source(_make_ref(pdf_path=pdf_file, abstract=LONG_ABSTRACT,
                                                   identity_status="mismatch"))
    assert with_abstract.coverage == "abstract_only" and with_abstract.doc is not None
    without = await resolve_source(_make_ref(pdf_path=pdf_file, identity_status="mismatch"))
    assert without.doc is None and without.cannot_verify_reason == "reference_mismatch"


def test_abstract_source_field_stored() -> None:
    ref = Reference(id=1, raw_text="test", abstract_text="Some abstract",
                    abstract_source="semantic_scholar")
    assert ref.abstract_source == "semantic_scholar"
    assert ref.abstract_text == "Some abstract"


def test_abstract_confidence_cap() -> None:
    from refcheck.stages.verify_claims.cascade_helpers import ABSTRACT_CONFIDENCE_CAP

    assert ABSTRACT_CONFIDENCE_CAP == 0.60
