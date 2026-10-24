"""Eval parity for cited_for: gold rows and Citation-Integrity rows get the cited_for
the current detection rules give (V5.7 #10 / #14 reach the eval). Synthetic text."""

import pytest

from refcheck.stages.detect_citations.cited_for_rescope import (
    gold_cited_for,
    numbered_text,
    placeholder_scope,
)

SENTENCE = ("As light frames (Hale et al., 2017) with folding poles (Pike et al., "
            "2025) and low cost (Bain et al., 2024a), modern tents protect hikers.")
SCOPE = ("As light frames with folding poles and low cost, modern tents protect "
         "hikers")


class TestGold:
    def test_recorded_whole_sentence_becomes_the_positional_clause(self) -> None:
        got = gold_cited_for(SENTENCE, SCOPE, SCOPE, "Pike, H. H.", 2025)
        assert got == "with folding poles, modern tents protect hikers"

    def test_year_letter_and_empty_stored_value(self) -> None:
        got = gold_cited_for(SENTENCE, SCOPE, "", "Bain, C.", 2024)
        assert got == "low cost, modern tents protect hikers"

    def test_switch_off_keeps_the_recorded_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REFCHECK_V57_DISABLE", "10")
        assert gold_cited_for(SENTENCE, SCOPE, SCOPE, "Pike, H. H.", 2025) == SCOPE

    @pytest.mark.parametrize("stored,author,year", [
        ("a value older code recorded", "Pike, H. H.", 2025),  # not reproducible
        (SCOPE, "Nobody, A.", 2025),  # reference not in the sentence
        (SCOPE, "Pike, H. H.", None),
    ])
    def test_left_alone(self, stored: str, author: str, year: int | None) -> None:
        assert gold_cited_for(SENTENCE, SCOPE, stored, author, year) == stored

    def test_narrowed_clause_unchanged(self) -> None:
        sentence = ("Gels reduce fibrosis (Smith et al., 2020) and aid survival "
                    "(Jones et al., 2021).")
        scope = "Gels reduce fibrosis and aid survival"
        assert gold_cited_for(sentence, scope, "aid survival", "Jones, K.", 2021) == "aid survival"


class TestCitationIntegrity:
    def test_placeholders_become_numbered_brackets(self) -> None:
        raw = ("A [<|other_cit|>], B (<|multi_cit|>) and C <|cit|>. D [<|other_cit|>, "
               "<|cit|>]")
        assert numbered_text(raw) == "A [2], B [1, 3] and C [1]. D [4, 1]"

    def test_enumeration_item_with_the_shared_clause(self) -> None:
        raw = ("Microbes shift in disease. ... Such links were found in many conditions, "
               "including colitis [<|other_cit|>], hepatitis [<|other_cit|>], and "
               "arthritis [<|cit|>].")
        got = placeholder_scope(raw)
        assert got is not None and got.changed
        assert got.sentence.startswith("Such links were found")
        assert got.before == ("Such links were found in many conditions, including colitis, "
                              "hepatitis, and arthritis")
        assert got.after == "Such links were found in many conditions, including arthritis"

    def test_single_marker_sentence_is_unchanged(self) -> None:
        got = placeholder_scope("Gels reduce IL-6 in mice [<|cit|>].")
        assert got is not None and not got.changed
        assert got.after == got.scope == "Gels reduce IL-6 in mice"

    def test_no_cited_marker(self) -> None:
        assert placeholder_scope("Gels reduce IL-6 [<|other_cit|>].") is None
