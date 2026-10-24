"""Re-match must not link a PDF that only CITES the reference, or a companion paper.

Regressions (review of the re-match pass, synthetic PDFs only): a 1-page
commentary printing its own DOI and citing the reference's DOI on page 1, a
2-page letter citing the DOI in its page-2 reference list, and a companion
paper whose title differs from the reference's by one key word ("swine" vs
"rats") were all linked to the reference.
"""

from pathlib import Path

from refcheck.stages.match_pdfs.doi_placement import doi_placement, in_citation_entry
from refcheck.stages.match_pdfs.pdf_profile import build_profile
from refcheck.stages.match_pdfs.rematch import rematch_pdfs
from refcheck.stages.match_pdfs.rematch_evidence import assess, decide
from tests.unit.rematch_fakes import DOI_A, PROSE, TITLE_A, GateStub, article, ref

_CITED = f"Doe J, Roe K. {TITLE_A}. Synth J. 2021;3:1-9. doi:{DOI_A}"
_COMMENT = "Graft tolerance needs local immunosuppression: a commentary"
_LETTER = "Response to Doe and Roe on hydrogels that release tacrolimus locally"
_RATS = "Injectable gel depot of drug Z prolongs hind limb allograft survival in rats"
_SWINE = _RATS.replace("in rats", "in swine")


def test_commentary_citing_the_doi_on_page_one_is_not_linked(tmp_path: Path) -> None:
    body = "Short commentary text on local delivery. " * 6 + f"\nReferences\n1. {_CITED}\n"
    article(tmp_path / "comment.pdf", title=_COMMENT, doi_line="doi:10.9999/jsc.2019.77",
            authors="Ann Lee", year="2021", pages=1, body=body)
    assert rematch_pdfs([ref(1)], [], tmp_path, GateStub()).records == []


def test_own_doi_printed_first_blocks_a_later_reference_doi() -> None:
    page = f"{_COMMENT}\nAnn Lee 2021\ndoi:10.9999/jsc.2019.77\n{PROSE[:300]}\n{_CITED}"
    ev = assess(ref(1), build_profile(Path("x.pdf"), [page, PROSE]))
    assert not ev.doi_primary and ev.doi_conflict and decide(ref(1), ev) is None


def test_letter_citing_the_doi_on_page_two_is_not_linked(tmp_path: Path) -> None:
    article(tmp_path / "letter.pdf", title=_LETTER, doi_line="", authors="Ann Lee",
            year="2021", pages=2, page2=f"References\n[1] {_CITED}\n{PROSE[:400]}")
    assert rematch_pdfs([ref(1)], [], tmp_path, GateStub()).records == []


def test_page_two_doi_needs_the_title_on_page_one() -> None:
    page1 = f"{_LETTER}\nAnn Lee 2021\n{PROSE[:600]}"  # Doe is on page 1, the title is not
    ev = assess(ref(1), build_profile(Path("x.pdf"), [page1, f"Doe 2021 {DOI_A}\n{PROSE}"]))
    assert ev.doi_page == 2 and ev.doi_primary and ev.author_found
    assert decide(ref(1), ev) is None


def test_citation_entries_and_reference_lists_are_not_the_own_doi() -> None:
    text = f"Header\n[12] Smith A, Jones B. Paper. 2018;\n5:1-10. doi:{DOI_A}"
    assert in_citation_entry(text, text.index("doi:"))
    assert not in_citation_entry(f"1. Introduction\nThe paper doi:{DOI_A}", 30)
    listed = build_profile(Path("x.pdf"), [f"Title\nReferences\nDoe J. doi:{DOI_A}", PROSE])
    assert doi_placement(DOI_A, listed).page == 0
    assert doi_placement(DOI_A, build_profile(Path("x.pdf"), [f"T doi:{DOI_A}", ""])).page == 1


def test_companion_paper_one_key_word_apart_is_not_linked(tmp_path: Path) -> None:
    body = "In earlier work in rats the depot prolonged survival. " * 10
    article(tmp_path / "swine.pdf", title=_SWINE, doi_line="", body=body)
    reference = ref(1, title=_RATS, doi=None)
    ev = assess(reference, build_profile(Path("x.pdf"), [f"{_SWINE}\nJane Doe 2021\n{body}"]))
    assert ev.title_alignment >= 90 and not ev.title_words_aligned
    assert decide(reference, ev) is None
    assert rematch_pdfs([reference], [], tmp_path, GateStub()).records == []


def test_plural_variant_of_a_title_word_still_matches() -> None:
    reference = ref(1, title=_RATS, doi=None)
    page = f"{_RATS.replace('allograft', 'allografts')}\nJane Doe 2021\n{PROSE}"
    ev = assess(reference, build_profile(Path("x.pdf"), [page]))
    assert ev.title_words_aligned and decide(reference, ev) == "rematch_title"
