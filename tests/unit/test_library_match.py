"""Library re-match (V5.8, G3): a library PDF stands for a reference only on the upload
re-match evidence rules; never a mismatch, supplement, scan, own rejected copy or an
ambiguous pick. Synthetic PDFs only."""

import shutil
from pathlib import Path

from refcheck.stages.match_pdfs.library_match import match_in_library
from refcheck.stages.match_pdfs.rematch_models import PdfReader
from tests.unit.rematch_fakes import (
    DOI_B,
    OTHER_PROSE,
    TITLE_B,
    GateStub,
    article,
    ref,
    scanned,
    supplement,
)


def _lib(tmp_path: Path) -> Path:
    lib = tmp_path / "library"
    lib.mkdir()
    return lib


def test_library_pdf_printing_the_doi_is_linked(tmp_path: Path) -> None:
    pdf = article(_lib(tmp_path) / "doi_abc.pdf")
    match = match_in_library(ref(1), [], [pdf], [ref(1)], PdfReader(), GateStub(), "no_pdf")
    assert match is not None
    assert (match.method, match.reason, Path(match.pdf_path).name) == (
        "library_doi", "no_pdf", "doi_abc.pdf")


def test_title_route_needs_a_verified_identity(tmp_path: Path) -> None:
    pdf = article(_lib(tmp_path) / "nodoi.pdf", doi_line="")
    reader = PdfReader()
    unverified = match_in_library(ref(2), [], [pdf], [ref(2)], reader,
                                  GateStub("unverified"), "no_pdf")
    verified = match_in_library(ref(2), [], [pdf], [ref(2)], reader, GateStub(), "no_pdf")
    assert unverified is None
    assert verified is not None and verified.method == "library_title"


def test_keyed_copy_without_evidence_needs_a_verified_identity(tmp_path: Path) -> None:
    # Title on page 1 but no author line: the evidence rules fail, the key alone does not.
    pdf = article(_lib(tmp_path) / "doi_key.pdf", doi_line="", authors="Consortium")
    reader = PdfReader()
    keyed = match_in_library(ref(3), [pdf], [pdf], [ref(3)], reader, GateStub(), "no_pdf")
    assert keyed is not None and keyed.method == "library_key"
    assert match_in_library(ref(3), [pdf], [pdf], [ref(3)], reader,
                            GateStub("unverified"), "no_pdf") is None
    assert match_in_library(ref(3), [], [pdf], [ref(3)], reader, GateStub(), "no_pdf") is None


def test_identity_mismatch_is_never_linked_even_when_keyed(tmp_path: Path) -> None:
    pdf = article(_lib(tmp_path) / "doi_key.pdf")
    gate = GateStub("mismatch")
    assert match_in_library(ref(4), [pdf], [pdf], [ref(4)], PdfReader(), gate,
                            "identity_mismatch") is None


def test_wrong_paper_stored_under_the_key_is_rejected(tmp_path: Path) -> None:
    # A poisoned library: an earlier run stored another paper under this DOI's key.
    wrong = article(_lib(tmp_path) / "doi_key.pdf", title=TITLE_B, doi_line=f"doi: {DOI_B}")
    gate = GateStub(doi_key="mismatch")
    assert match_in_library(ref(5), [wrong], [wrong], [ref(5)], PdfReader(), gate,
                            "identity_mismatch") is None


def test_supplement_and_scan_are_never_linked(tmp_path: Path) -> None:
    lib = _lib(tmp_path)
    si = supplement(lib / "doi_si.pdf")
    scan = scanned(lib / "scan.pdf")
    reader = PdfReader()
    assert match_in_library(ref(6), [si], [si, scan], [ref(6)], reader, GateStub(),
                            "supplement") is None


def test_copy_of_the_rejected_upload_is_skipped(tmp_path: Path) -> None:
    upload = article(tmp_path / "upload.pdf")
    copy = _lib(tmp_path) / "doi_key.pdf"
    shutil.copy2(upload, copy)
    rejected = ref(7, pdf_path=upload)
    gate = GateStub()  # even a gate that would accept it: same bytes as the rejected PDF
    assert match_in_library(rejected, [copy], [copy], [rejected], PdfReader(), gate,
                            "identity_mismatch") is None


def test_two_different_papers_are_ambiguous(tmp_path: Path) -> None:
    lib = _lib(tmp_path)
    one = article(lib / "one.pdf", doi_line="")
    two = article(lib / "two.pdf", doi_line="", body=OTHER_PROSE)
    assert match_in_library(ref(8), [], [one, two], [ref(8)], PdfReader(), GateStub(),
                            "no_pdf") is None


def test_two_copies_of_one_paper_are_not_ambiguous(tmp_path: Path) -> None:
    lib = _lib(tmp_path)
    keyed = article(lib / "doi_key.pdf")
    other = lib / "copy.pdf"
    shutil.copy2(keyed, other)
    match = match_in_library(ref(9), [keyed], [keyed, other], [ref(9)], PdfReader(),
                             GateStub(), "no_pdf")
    assert match is not None and match.method == "library_doi"


def test_unrelated_library_pdfs_are_not_identity_checked(tmp_path: Path) -> None:
    lib = _lib(tmp_path)
    other = article(lib / "other.pdf", title=TITLE_B, doi_line=f"doi: {DOI_B}")
    gate = GateStub()
    assert match_in_library(ref(10), [], [other], [ref(10)], PdfReader(), gate,
                            "no_pdf") is None
    assert gate.calls == []  # the evidence check spares the identity read
