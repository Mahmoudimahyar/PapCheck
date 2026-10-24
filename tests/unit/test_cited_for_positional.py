"""V5.7 #10: positional attribution of phrases in multi-marker sentences.

Regression pattern: "As light frames (R1) with folding poles (R2), low cost (R3) and
the ability to resist wind (R4), tents protect hikers." left every marker
on the whole sentence, so R1 was judged on R4's phrase too and came back partial.
Each reference now keeps its own phrase plus the shared main clause. Synthetic text.
"""

import pytest

from refcheck.models.citation import VerificationUnit
from refcheck.stages.detect_citations.cited_for_positional import positional_clause, tidy
from refcheck.stages.detect_citations.detector import detect_in_paragraph
from refcheck.stages.detect_citations.scope_resolver import resolve_scopes

CHAIN = (
    "As light frames (Hale et al., 2017) with folding poles (Bain et al., 2024; "
    "Pike et al., 2025), low cost (Bain et al., 2024) and the ability to resist strong "
    "wind (Zorn et al., 2020), modern tents can shelter hikers while saving pack "
    "space."
)
SHARED = "modern tents can shelter hikers while saving pack space"


def _units(text: str) -> list[VerificationUnit]:
    """One reference id per distinct (first author, year, number)."""
    ids: dict[tuple[str, str | None, int | None], int] = {}
    cits = [c.model_copy(update={"reference_id": ids.setdefault(
        (c.authors[0] if c.authors else "", c.year, c.number), len(ids) + 1)})
        for c in detect_in_paragraph(text, para_idx=0, section="Introduction")]
    return resolve_scopes(cits)


def _by_marker(units: list[VerificationUnit]) -> dict[str, str]:
    return {u.citation_marker: u.cited_for for u in units}


class TestNounPhraseChain:
    def test_each_reference_keeps_its_phrase_and_the_shared_clause(self) -> None:
        got = _by_marker(_units(CHAIN))
        assert got["(Hale et al., 2017)"] == f"As light frames, {SHARED}"
        assert got["(Pike et al., 2025)"] == f"with folding poles, {SHARED}"
        assert got["(Zorn et al., 2020)"] == f"the ability to resist strong wind, {SHARED}"

    def test_a_reference_cited_twice_keeps_both_phrases(self) -> None:
        bain = {u.cited_for for u in _units(CHAIN) if u.citation_marker.startswith("(Bain")}
        assert bain == {f"with folding poles, low cost, {SHARED}"}

    def test_scope_stays_the_whole_sentence(self) -> None:
        assert all("resist strong wind" in u.scope_text for u in _units(CHAIN))

    def test_switch_off_restores_the_whole_sentence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REFCHECK_V57_DISABLE", "3,10")
        assert all(u.cited_for == u.scope_text for u in _units(CHAIN))


class TestEnumerations:
    def test_list_after_a_cue_word(self) -> None:
        got = _by_marker(_units(
            "Such links have been found in many conditions, including colitis [2], "
            "hepatitis [3], and arthritis [4]."))
        assert got["[3]"] == "Such links have been found in many conditions, including hepatitis"
        assert got["[4]"] == "Such links have been found in many conditions, including arthritis"

    def test_list_governed_by_a_preposition(self) -> None:
        got = _by_marker(_units("Projections carry input from motor [1], auditory [2], "
                                "and visual [3] cortex."))
        assert got["[2]"] == "Projections carry input from auditory cortex"
        assert got["[3]"] == "Projections carry input from visual cortex"

    def test_items_with_their_own_preposition_are_not_cut(self) -> None:
        units = _units("Antibodies acquired by infection [2] or through vaccination [1] "
                       "protect against disease.")
        cited = next(u for u in units if u.citation_marker == "[1]")
        assert cited.cited_for == cited.scope_text  # never "acquired by through vaccination"


class TestNeverChanged:
    @pytest.mark.parametrize("text", [
        "Hydrogels are biocompatible and reduce scarring (Ames et al., 2020).",
        "Gels (Lee et al., 2019) and films (Lee et al., 2019) reduce scarring.",
        "Hydrogels (Smith et al., 2020) are widely used, and alginate (Jones et al., 2021) "
        "is common.",
        "Gels (Kim et al., 2020) and films (Roe et al., 2021) lowered IL-6 by 20 and 30%, "
        "respectively.",
        "Islets (Kim et al., 2020) and gels (Roe et al., 2021) adapted from Ames et al. (2019).",
        "In islet transplantation (Lee et al., 2019), hydrogels improve engraftment and "
        "reduce hypoxia (Smith et al., 2020).",
    ])
    def test_whole_sentence_kept(self, text: str) -> None:
        for unit in _units(text):
            if not unit.citation_marker.startswith("(Smith"):
                assert unit.cited_for == unit.scope_text, unit.citation_marker

    def test_markers_that_close_clauses_keep_their_clause(self) -> None:
        got = _by_marker(_units("Gels reduce fibrosis (Smith et al., 2020) and aid "
                                "survival (Jones et al., 2021)."))
        assert got == {"(Smith et al., 2020)": "Gels reduce fibrosis",
                       "(Jones et al., 2021)": "aid survival"}


class TestPositionalClause:
    def test_no_change_without_another_reference(self) -> None:
        sentence = "Gels [1] and films [2] reduce scarring."
        groups = [(5, 8), (19, 22)]
        assert positional_clause(sentence, groups, [True, True], 0) is None
        assert positional_clause(sentence, groups, [True, False], 0) == \
            "Gels reduce scarring."

    def test_tidy_joins_leftover_punctuation(self) -> None:
        assert tidy("A ,  , B ;") == "A, B;"
