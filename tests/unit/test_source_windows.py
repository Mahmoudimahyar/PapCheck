"""Tests for sentence splitting, windowing and heading classification."""

import pytest

from refcheck.stages.verify_claims.source_cleaning import (
    classify_heading,
    is_caption,
    join_lines,
    sanitize_source_text,
)
from refcheck.stages.verify_claims.source_windows import split_sentences, window_bounds


def _sents(text: str) -> list[str]:
    return [s for _, s in split_sentences(text)]


class TestSplitSentences:
    def test_basic_split_with_offsets(self) -> None:
        text = "Mice were treated daily. Levels fell sharply afterwards. Nothing else changed here."
        parts = split_sentences(text)
        assert [s for _, s in parts] == [
            "Mice were treated daily.", "Levels fell sharply afterwards.",
            "Nothing else changed here.",
        ]
        assert all(text[off:off + len(s)] == s for off, s in parts)

    @pytest.mark.parametrize("text", [
        "As reported by Smith et al. (2010) the effect was large and robust overall.",
        "The effect is shown in Fig. 2 and was large in all treated groups.",
        "Doses (e.g. 5 mg) were given orally to all of the enrolled patients.",
        "The mean was 3.5 units in the treated group of the cohort studied.",
        "Data from the U.S. Army cohort were analysed by the study team.",
    ])
    def test_does_not_split_on_abbreviations_or_decimals(self, text: str) -> None:
        assert _sents(text) == [text]

    def test_splits_after_numeric_citation(self) -> None:
        text = "Autophagy protects neurons in mice.[12] Rapamycin increased it further in vivo."
        assert len(_sents(text)) == 2

    def test_long_run_on_text_is_capped(self) -> None:
        text = " ".join(f"value{i}" for i in range(200))
        parts = _sents(text)
        assert len(parts) >= 3 and all(len(p.split()) <= 80 for p in parts)

    def test_short_fragments_merge_into_next_sentence(self) -> None:
        parts = _sents("Results. Treatment reduced the tumour volume in all mice.")
        assert parts == ["Results. Treatment reduced the tumour volume in all mice."]


class TestWindowBounds:
    @pytest.mark.parametrize(("n", "expected"), [
        (0, []), (1, [(0, 1)]), (2, [(0, 2)]), (3, [(0, 3)]), (4, [(0, 3), (2, 4)]),
        (5, [(0, 3), (2, 5)]), (6, [(0, 3), (2, 5), (4, 6)]),
    ])
    def test_three_sentence_stride_two(self, n: int, expected: list[tuple[int, int]]) -> None:
        assert window_bounds(n) == expected

    def test_every_sentence_covered(self) -> None:
        for n in range(1, 30):
            covered = {i for lo, hi in window_bounds(n) for i in range(lo, hi)}
            assert covered == set(range(n))


class TestHeadings:
    @pytest.mark.parametrize(("line", "action"), [
        ("1. Introduction", "Introduction"), ("2 Materials and Methods", "Methods"),
        ("RESULTS", "Results"), ("## Discussion", "Discussion"), ("Conclusions", "Conclusion"),
        ("References", "drop"), ("Acknowledgements", "drop"), ("Author contributions", "drop"),
        ("Funding", "drop"), ("STAR★Methods", "Methods"), ("Supplementary Material", "other"),
    ])
    def test_recognised(self, line: str, action: str) -> None:
        heading = classify_heading(line)
        assert heading is not None and heading.action == action

    @pytest.mark.parametrize("line", [
        "results.", "previous results showed", "Results were robust across all cohorts here.",
    ])
    def test_prose_is_not_a_heading(self, line: str) -> None:
        assert classify_heading(line) is None

    def test_markdown_level(self) -> None:
        heading = classify_heading("### Background")
        assert heading is not None and heading.level == 3 and heading.action == "Introduction"

    def test_captions(self) -> None:
        assert is_caption("Figure 2. Amyloid levels in mice.")
        assert is_caption("Table 1 Baseline characteristics")
        assert not is_caption("Table 2 shows the baseline characteristics.")


class TestCleaning:
    def test_sanitize(self) -> None:
        raw = "eﬃcacy\x00 of soft­hyphen\r\n\n\n\nnext"
        assert sanitize_source_text(raw) == "efficacy of softhyphen\n\nnext"

    def test_join_lines_dehyphenates_lowercase_only(self) -> None:
        # A capital or digit next to the line-end hyphen marks a real compound:
        # the hyphen stays and no space is inserted ("IL-6", not "IL- 6").
        assert join_lines(["aggre-", "gation of", "IL-", "6"]) == "aggregation of IL-6"
        assert join_lines(["CD4+ T-", "cell and VX-", "880 with anti-", "CD3"]) \
            == "CD4+ T-cell and VX-880 with anti-CD3"
        assert join_lines(["Fig. 2 -", "left"]) == "Fig. 2 - left"  # spaced dash untouched

    def test_sanitize_nfkc_folds_compatibility_characters(self) -> None:
        # M9: ligatures, full-width forms and the micro sign must reach BM25,
        # embeddings and quote validation in the same spelling as the claim.
        raw = "hyperﬁbrosis ﬂuid ﬀ ﬃ ﬄ， 5 µm ＣＤ４"
        assert sanitize_source_text(raw) == "hyperfibrosis fluid ff ffi ffl, 5 μm CD4"
        # an ellipsis is not turned into "..." (that would end sentences)
        assert sanitize_source_text("levels rose… Then") == "levels rose… Then"
