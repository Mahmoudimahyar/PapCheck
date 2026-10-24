"""Tests for the in-house BM25 index."""

import pytest

from refcheck.stages.verify_claims.bm25 import BM25Index, stem, tokenize


class TestStemAndTokenize:
    @pytest.mark.parametrize("word", ["reduce", "reduces", "reduced", "reducing"])
    def test_inflections_meet(self, word: str) -> None:
        assert stem(word) == "reduc"

    def test_plurals(self) -> None:
        assert stem("studies") == stem("study")
        assert stem("cells") == "cell"
        assert stem("virus") == "virus"  # -us is not a plural

    def test_tokenize_drops_stopwords_keeps_numbers_and_greek(self) -> None:
        tokens = tokenize("The levels of Aβ42 were reduced by 40% in mice")
        assert "the" not in tokens and "of" not in tokens
        assert "aβ42" in tokens and "40" in tokens and "mice" in tokens


DOCS = [
    "Rapamycin reduced amyloid beta levels in transgenic mice.",
    "Cognitive deficits were measured with the Morris water maze.",
    "Statistical analysis used two-way ANOVA with post hoc tests.",
    "Amyloid plaques and amyloid beta accumulate with age in mice.",
]


class TestBM25Index:
    def test_relevant_document_ranks_first(self) -> None:
        index = BM25Index(DOCS)
        ranked = index.top_n("rapamycin reduces amyloid beta", 3)
        assert ranked[0][0] == 0
        assert all(score > 0 for _, score in ranked)

    def test_rare_terms_weigh_more(self) -> None:
        index = BM25Index(DOCS)
        assert index.idf("rapamycin") > index.idf("amyloid")

    def test_no_overlap_gives_no_results(self) -> None:
        assert BM25Index(DOCS).top_n("quantum chromodynamics", 5) == []

    def test_empty_index(self) -> None:
        index = BM25Index([])
        assert index.rank_all("anything") == []

    def test_rank_all_orders_by_score(self) -> None:
        scores = [s for _, s in BM25Index(DOCS).rank_all("amyloid mice")]
        assert scores == sorted(scores, reverse=True)


class TestCompatibilityCharacters:
    """M9: PDF ligatures / micro sign / full-width forms must not split vocabularies."""

    def test_ligature_and_plain_spelling_share_tokens(self) -> None:
        assert tokenize("hyperﬁbrosis and ﬂuid") == tokenize("hyperfibrosis and fluid")

    def test_micro_sign_and_fullwidth_digits(self) -> None:
        assert tokenize("pores of 5 µm in ＣＤ４ cells") == tokenize("pores of 5 μm in CD4 cells")

    def test_ligature_passage_found_by_plain_query(self) -> None:
        index = BM25Index(["Capsules prevent hyperﬁbrosis around the graft.",
                           "Insulin secretion was measured daily."])
        assert index.top_n("hyperfibrosis around grafts", 1)[0][0] == 0
