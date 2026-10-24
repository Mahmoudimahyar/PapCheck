"""Re-match evidence: whitespace-tolerant DOIs, page-1 title alignment, author/year."""

from pathlib import Path

import pytest

from refcheck.stages.match_pdfs.doi_placement import doi_page, doi_pattern
from refcheck.stages.match_pdfs.pdf_profile import (
    PdfProfile,
    build_profile,
    normalized_variants,
)
from refcheck.stages.match_pdfs.rematch_evidence import (
    assess,
    content_words,
    decide,
    first_author_surname,
)
from refcheck.stages.match_pdfs.rematch_select import same_reference_paper
from refcheck.stages.match_pdfs.title_window import stem, title_match
from tests.unit.rematch_fakes import DOI_A, PROSE, TITLE_A, TITLE_B, ref

_HEAD = f"{TITLE_A}\nJane Doe, Kim Roe\nPublished 2021\n"


def _profile(page1: str, page2: str = PROSE) -> PdfProfile:
    return build_profile(Path("x.pdf"), [page1, page2])


@pytest.mark.parametrize("printed", [
    "https://doi.org/10.5555/SYNTH\n.01234-56.", "DOI: 10.5555=synth.01234-56",
    "doi:10.5555/synth.01234- 56", "(10.5555/synth.01234-56)",
])
def test_doi_found_despite_breaks(printed: str) -> None:
    pattern = doi_pattern(DOI_A)
    assert pattern is not None and pattern.search(f"Cite this {printed} Copyright")


@pytest.mark.parametrize("printed", ["10.5555/synth.01234-567", "910.5555/synth.01234-56",
                                     "10.5555/synth.01234"])
def test_longer_or_shorter_doi_is_not_the_reference(printed: str) -> None:
    pattern = doi_pattern(DOI_A)
    assert pattern is not None and not pattern.search(f"See {printed} here")


def test_doi_pattern_needs_a_doi() -> None:
    assert doi_pattern("") is None and doi_pattern("not a doi") is None


def test_doi_page_counts_metadata_as_page_one() -> None:
    profile = build_profile(Path("x.pdf"), [f"meta {DOI_A}\n{PROSE}", PROSE])
    assert doi_page(DOI_A, profile) == 1
    assert doi_page(DOI_A, build_profile(Path("x.pdf"), [PROSE, f"x {DOI_A}"])) == 2
    assert doi_page(None, profile) == 0


def test_hyphenated_line_breaks_read_both_ways() -> None:
    assert normalized_variants("cyto-\nkine stress") == ["cyto kine stress", "cytokine stress"]
    assert normalized_variants("Plain  Text.") == ["plain text"]


@pytest.mark.parametrize(("authors", "surname"), [
    (["Roe, W.", "X"], "roe"), (["W. Roe"], "roe"), (["van Dam, B. J."], "van dam"),
    ([], ""), ([" "], ""),
])
def test_first_author_surname(authors: list[str], surname: str) -> None:
    assert first_author_surname(authors) == surname


def test_content_words_drop_stopwords() -> None:
    assert content_words("The role of IL-6 in graft and host") == ["role", "graft", "host"]


def test_doi_on_page_one_is_primary() -> None:
    ev = assess(ref(1), _profile(f"{_HEAD}https://doi.org/{DOI_A}\n{PROSE}"))
    assert ev.doi_primary and not ev.doi_conflict and decide(ref(1), ev) == "rematch_doi"


def test_doi_on_page_two_counts_only_without_another_doi_on_page_one() -> None:
    alone = assess(ref(1), _profile(f"{_HEAD}{PROSE}", f"doi {DOI_A}\n{PROSE}"))
    assert alone.doi_primary and decide(ref(1), alone) == "rematch_doi"
    cited = assess(ref(1), _profile(f"{TITLE_B}\ndoi 10.5555/other.9\n{PROSE}",
                                    f"[12] Doe J. {DOI_A}"))
    assert not cited.doi_primary and cited.doi_conflict and decide(ref(1), cited) is None


def test_another_printed_doi_blocks_the_title_route() -> None:
    ev = assess(ref(1), _profile(f"{_HEAD}https://doi.org/10.5555/other.9\n{PROSE}"))
    assert ev.doi_conflict and ev.title_alignment == 100 and decide(ref(1), ev) is None


def test_preprint_doi_is_no_conflict() -> None:
    ev = assess(ref(1), _profile(f"{_HEAD}bioRxiv 10.1101/2020.01.01.123456\n{PROSE}"))
    assert not ev.doi_conflict and decide(ref(1), ev) == "rematch_title"


def test_title_words_scattered_over_the_abstract_do_not_count() -> None:
    words = " ".join(reversed(TITLE_A.split()))
    ev = assess(ref(1, doi=None), _profile(f"Other heading\nJane Doe 2021\n{words}. {PROSE}"))
    assert ev.title_coverage == 1.0 and ev.title_alignment < 90
    assert decide(ref(1, doi=None), ev) is None


def test_title_route_needs_author_and_year() -> None:
    page = f"{TITLE_A}\nKim Roe\nPublished 2021\n{PROSE}"
    assert decide(ref(1, doi=None), assess(ref(1, doi=None), _profile(page))) is None
    old = ref(1, doi=None, year=2015)
    assert decide(old, assess(old, _profile(_HEAD + PROSE))) is None


def test_title_route_without_authors_needs_year_and_close_alignment() -> None:
    anonymous = ref(1, doi=None, authors=[])
    assert decide(anonymous, assess(anonymous, _profile(_HEAD + PROSE))) == "rematch_title"
    undated = ref(1, doi=None, authors=[], year=None)
    assert decide(undated, assess(undated, _profile(_HEAD + PROSE))) is None


def test_short_titles_never_match_on_title() -> None:
    short = ref(1, title="Hand transplantation outcomes", doi=None)
    page = f"Hand transplantation outcomes\nJane Doe 2021\n{PROSE}"
    assert decide(short, assess(short, _profile(page))) is None


def test_same_reference_paper() -> None:
    assert same_reference_paper(ref(1), ref(2, duplicate_of=1))
    assert same_reference_paper(ref(1), ref(2))  # same DOI
    assert not same_reference_paper(ref(1), ref(2, doi="10.5555/other.9"))
    assert same_reference_paper(ref(1, doi=None), ref(2, doi=None))
    assert not same_reference_paper(ref(1, doi=None), ref(2, doi=None, year=2020))
    assert not same_reference_paper(ref(1, title=""), ref(2, title="", doi=None))


_COATED = "Coated cell clusters reverse hyperglycemia in diabetic rats"


@pytest.mark.parametrize("printed", [
    "Uncoated cell clusters reverse hyperglycemia in diabetic rats",
    "Coated cell clusters reverse hypoglycemia in diabetic rats",
])
def test_title_word_with_an_opposite_prefix_is_not_aligned(printed: str) -> None:
    score, aligned = title_match(_COATED, normalized_variants(f"{printed}\nJane Doe 2021"))
    assert score >= 90 and not aligned


@pytest.mark.parametrize(("printed", "aligned"), [
    ("Coated cell cluster reverses hyperglycemia in diabetic rat", True),  # plurals
    ("Coated cell clusters reverse hyperglycaemias in diabetic rats", False),  # another word
])
def test_title_key_words_match_exactly_or_by_light_stem(printed: str, aligned: bool) -> None:
    assert title_match(_COATED, normalized_variants(f"{printed}\nJane Doe 2021"))[1] is aligned
    assert [stem(w) for w in ("randomised", "tumours", "studies", "viruses", "reverses")] == \
        ["randomized", "tumor", "study", "virus", "reverse"]
