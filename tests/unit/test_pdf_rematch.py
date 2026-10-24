"""Re-match before abstract fallback: references without a usable PDF get a second
chance against the uploaded PDFs (printed DOI, page-1 title + author + year)."""

from pathlib import Path
from unittest.mock import patch

from refcheck.stages.match_pdfs import rematch as rematch_module
from refcheck.stages.match_pdfs.rematch import rematch_or_keep, rematch_pdfs
from tests.unit.rematch_fakes import (
    DOI_B,
    OTHER_PROSE,
    TITLE_B,
    GateStub,
    article,
    held,
    ref,
    scanned,
    supplement,
)


def test_broken_doi_line_is_rematched_by_doi(tmp_path: Path) -> None:
    # Garbage metadata title and a DOI split by a line break defeat the first pass.
    article(tmp_path / "SM-1.pdf", doi_line="https://doi.org/10.5555/SYNTH\n.01234-56",
            meta_title="SM-AMAC000000 1..16")
    out = rematch_pdfs([ref(11)], [], tmp_path, GateStub())
    assert [(r.reference_id, r.method, r.reason) for r in out.records] == [
        (11, "rematch_doi", "no_pdf")]
    result = out.results[0]
    assert Path(result.pdf_path or "").name == "SM-1.pdf"
    assert result.match_method == "rematch_doi" and not result.needs_user_confirmation


def test_doi_with_equals_sign_for_slash(tmp_path: Path) -> None:
    article(tmp_path / "liebert.pdf", doi_line="DOI: 10.5555=synth.01234-56")
    out = rematch_pdfs([ref(90)], [], tmp_path, GateStub("unverified"))
    assert [r.method for r in out.records] == ["rematch_doi"]  # DOI tolerates "unverified"


def test_title_author_year_on_page_one_without_doi(tmp_path: Path) -> None:
    article(tmp_path / "nodoi.pdf", doi_line="")
    out = rematch_pdfs([ref(5)], [], tmp_path, GateStub())
    assert [r.method for r in out.records] == ["rematch_title"]
    assert out.results[0].match_method == "rematch_title"


def test_title_only_link_needs_a_verified_identity(tmp_path: Path) -> None:
    article(tmp_path / "nodoi.pdf", doi_line="")
    assert rematch_pdfs([ref(5)], [], tmp_path, GateStub("unverified")).records == []


def test_identity_mismatch_blocks_even_a_printed_doi(tmp_path: Path) -> None:
    article(tmp_path / "other.pdf")
    assert rematch_pdfs([ref(5)], [], tmp_path, GateStub("mismatch")).records == []


def test_wrong_first_pass_pdf_is_replaced(tmp_path: Path) -> None:
    wrong = article(tmp_path / "wrong.pdf", title=TITLE_B, doi_line=f"doi: {DOI_B}")
    article(tmp_path / "right.pdf")
    out = rematch_pdfs([ref(34)], [held(34, wrong)], tmp_path, GateStub(wrong="mismatch"))
    record = out.records[0]
    assert (record.reason, Path(record.pdf_path).name) == ("identity_mismatch", "right.pdf")
    assert Path(record.replaced_pdf or "").name == "wrong.pdf"
    assert [Path(r.pdf_path or "").name for r in out.results] == ["right.pdf"]


def test_wrong_pdf_kept_when_no_other_upload_fits(tmp_path: Path) -> None:
    wrong = article(tmp_path / "wrong.pdf", title=TITLE_B, doi_line=f"doi: {DOI_B}")
    first = [held(22, wrong)]
    out = rematch_pdfs([ref(22)], first, tmp_path, GateStub(wrong="mismatch"))
    assert out.records == [] and out.rejected == {22: "identity_mismatch"}
    assert out.results == first


def test_supplement_never_linked_but_article_replaces_it(tmp_path: Path) -> None:
    si = supplement(tmp_path / "ab1c23456_si_001.pdf")
    first = [held(108, si)]
    alone = rematch_pdfs([ref(108)], first, tmp_path, GateStub())
    assert alone.records == [] and alone.rejected == {108: "supplement"}
    article(tmp_path / "article.pdf")
    out = rematch_pdfs([ref(108)], first, tmp_path, GateStub())
    assert [(r.reason, Path(r.pdf_path).name) for r in out.records] == [
        ("supplement", "article.pdf")]


def test_supplement_is_not_a_candidate(tmp_path: Path) -> None:
    supplement(tmp_path / "ab1c23456_si_001.pdf")
    assert rematch_pdfs([ref(7)], [], tmp_path, GateStub()).records == []
    supplement(tmp_path / "plain.pdf")  # same content, neutral name: still a supplement
    assert rematch_pdfs([ref(7)], [], tmp_path, GateStub()).records == []


def test_scanned_pdf_is_rejected_and_never_a_candidate(tmp_path: Path) -> None:
    scan = scanned(tmp_path / "scan.pdf")
    out = rematch_pdfs([ref(87)], [held(87, scan)], tmp_path, GateStub())
    assert out.rejected == {87: "scanned"} and out.records == []
    assert rematch_pdfs([ref(88)], [], tmp_path, GateStub()).records == []


def test_confidently_held_pdf_is_not_taken(tmp_path: Path) -> None:
    pdf = article(tmp_path / "a.pdf")
    other = ref(2, title=TITLE_B, doi="10.5555/other.1")  # holds a.pdf, a different work
    out = rematch_pdfs([ref(1), other], [held(2, pdf)], tmp_path, GateStub())
    assert out.records == [] and out.rejected == {1: "no_pdf"}


def test_unconfirmed_holder_does_not_block(tmp_path: Path) -> None:
    pdf = article(tmp_path / "a.pdf")
    other = ref(2, title=TITLE_B, doi="10.5555/other.1")
    out = rematch_pdfs([ref(1), other], [held(2, pdf, confirm=True)], tmp_path, GateStub())
    assert [r.reference_id for r in out.records] == [1]


def test_duplicate_reference_reuses_the_held_pdf(tmp_path: Path) -> None:
    pdf = article(tmp_path / "a.pdf")
    refs = [ref(51), ref(52, duplicate_of=51)]
    out = rematch_pdfs(refs, [held(51, pdf)], tmp_path, GateStub())
    assert [(r.reference_id, Path(r.pdf_path).name) for r in out.records] == [(52, "a.pdf")]


def test_two_different_papers_fitting_one_reference_are_ambiguous(tmp_path: Path) -> None:
    article(tmp_path / "abstract.pdf", doi_line="", pages=3)
    assert len(rematch_pdfs([ref(5)], [], tmp_path, GateStub()).records) == 1  # control
    article(tmp_path / "full.pdf", doi_line="", pages=5, body=OTHER_PROSE)
    assert rematch_pdfs([ref(5)], [], tmp_path, GateStub()).records == []


def test_copies_of_one_paper_are_not_ambiguous(tmp_path: Path) -> None:
    article(tmp_path / "copy (1).pdf")
    article(tmp_path / "copy.pdf")
    out = rematch_pdfs([ref(5)], [], tmp_path, GateStub())
    assert len(out.records) == 1


def test_pdf_fitting_two_works_equally_is_not_linked(tmp_path: Path) -> None:
    article(tmp_path / "nodoi.pdf", doi_line="", year="2020 2021")
    twins = [ref(1, doi=None, year=2020), ref(2, doi=None, year=2021)]
    assert len(rematch_pdfs(twins[:1], [], tmp_path, GateStub()).records) == 1  # control
    assert rematch_pdfs(twins, [], tmp_path, GateStub()).records == []


def test_printed_doi_breaks_a_title_tie(tmp_path: Path) -> None:
    article(tmp_path / "a.pdf")
    rival = ref(2, doi=None, year=2020)  # same title + author, no DOI: a weaker claim
    out = rematch_pdfs([ref(1), rival], [], tmp_path, GateStub())
    assert [r.reference_id for r in out.records] == [1]


def test_nothing_to_do(tmp_path: Path) -> None:
    pdf = article(tmp_path / "a.pdf")
    first = [held(1, pdf)]
    out = rematch_pdfs([ref(1)], first, tmp_path, GateStub())
    assert out.results == first and out.records == [] and out.rejected == {}
    assert rematch_pdfs([ref(1)], first, tmp_path / "missing", GateStub()).results == first


def test_failure_keeps_first_pass(tmp_path: Path) -> None:
    first = [held(1, tmp_path / "a.pdf")]
    with patch.object(rematch_module, "rematch_pdfs", side_effect=RuntimeError("boom")):
        out = rematch_or_keep([ref(1)], first, tmp_path, GateStub())
    assert out.results == first and out.records == []


def test_without_gate_title_route_still_needs_author_and_year(tmp_path: Path) -> None:
    article(tmp_path / "nodoi.pdf", title=TITLE_B, doi_line="", authors="Someone Else",
            year="1990")
    assert rematch_pdfs([ref(5, title=TITLE_B, doi=None)], [], tmp_path).records == []
