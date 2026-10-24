"""Tests for V5 passage retrieval (hybrid BM25/embeddings), pack assembly and rendering."""

import pytest

from refcheck.stages.verify_claims import retrieval_embed
from refcheck.stages.verify_claims.retriever import (
    bm25_pack,
    clean_query,
    expanded_pack,
    fuse_rrf,
    render_pack,
    retrieve,
)
from refcheck.stages.verify_claims.source_document import (
    build_abstract_document,
    build_source_document,
)
from refcheck.stages.verify_claims.source_models import SourceDocument

_FILLER = " ".join(
    f"Filler sentence {i} describes routine laboratory procedures and equipment."
    for i in range(60)
)
TEXT = (
    "## Abstract\n\nRapamycin was given to transgenic mice. Cognitive decline was prevented. "
    "Amyloid levels were lower after treatment.\n\n"
    "## Methods\n\n" + _FILLER + "\n\n"
    "## Results\n\nRapamycin reduced amyloid beta 42 by 40% in hippocampus. "
    "The reduction persisted for twelve weeks. Autophagy markers rose in neurons. "
    "Treated mice found the hidden platform faster. Untreated mice did not improve.\n\n"
    "## Discussion\n\nOur canine cohort tolerated the drug well. "
    + _FILLER.replace("Filler", "Other")
)


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    retrieval_embed.clear_embedding_cache()


@pytest.fixture
def doc() -> SourceDocument:
    return build_source_document(7, TEXT)


class TestHelpers:
    def test_rrf_rewards_agreement(self) -> None:
        fused = fuse_rrf([[1, 2, 3], [3, 1, 4]])
        assert [i for i, _ in fused][:2] == [1, 3]
        assert fused[0][1] == pytest.approx(1 / 61 + 1 / 62)

    @pytest.mark.parametrize(("raw", "clean"), [
        ("Autophagy protects neurons [46],", "Autophagy protects neurons ,"),
        ("as shown (3, 4) before", "as shown before"),
        ("typically cyclical36 due to #", "typically cyclical due to"),
        ("reported (Smith et al., 2010).", "reported ."),
    ])
    def test_clean_query(self, raw: str, clean: str) -> None:
        assert clean_query(raw) == clean


class TestBm25Packs:
    async def test_standard_pack_structure(self, doc: SourceDocument) -> None:
        pack = await retrieve("rapamycin reduced amyloid beta by 40%", doc, use_embeddings=False)
        assert pack.passages[0].id == "A"
        assert [p.id for p in pack.passages[1:]] == [f"P{i}" for i in range(1, len(pack.passages))]
        assert "40%" in pack.passages[1].text and pack.passages[1].section == "Results"
        assert pack.total_tokens <= 3000 and pack.coverage == "full_text"
        assert pack.retrieval_version.endswith(":bm25") and not pack.used_embeddings

    async def test_adjacent_windows_merge_without_duplicates(self, doc: SourceDocument) -> None:
        pack = await retrieve("rapamycin amyloid reduction autophagy platform", doc,
                              use_embeddings=False)
        results = [p for p in pack.passages if p.section == "Results"]
        assert len(results) == 1 and len(results[0].unit_idxs) >= 2
        assert results[0].text.count("Autophagy markers rose") == 1

    async def test_budget_respected_and_expanded_is_larger(self, doc: SourceDocument) -> None:
        small = await retrieve("laboratory procedures", doc, max_tokens=300, use_embeddings=False)
        big = await expanded_pack("laboratory procedures", doc, use_embeddings=False)
        assert small.total_tokens <= 300 < big.total_tokens <= 8000

    def test_abstract_only_pack(self) -> None:
        doc = build_abstract_document(3, "An abstract about rapamycin in mice. " * 5)
        pack = bm25_pack("rapamycin", doc)
        assert [p.id for p in pack.passages] == ["A"] and pack.coverage == "abstract_only"

    def test_empty_document_gives_empty_pack(self) -> None:
        pack = bm25_pack("anything", build_source_document(1, ""))
        assert pack.is_empty and pack.total_tokens == 0

    def test_long_abstract_truncated_to_400_tokens(self) -> None:
        long_abstract = "Rapamycin changed amyloid handling in the mouse brain. " * 80
        doc = build_source_document(2, TEXT, abstract_text=long_abstract)
        abstract = bm25_pack("amyloid", doc).passages[0]
        assert abstract.id == "A" and abstract.n_tokens <= 400

    def test_abstract_windows_not_repeated(self, doc: SourceDocument) -> None:
        pack = bm25_pack("cognitive decline prevented transgenic", doc)
        assert all(p.section != "Abstract" for p in pack.passages[1:])


class TestRender:
    def test_render_format(self, doc: SourceDocument) -> None:
        pack = bm25_pack("rapamycin reduced amyloid beta by 40%", doc)
        lines = render_pack(pack).split("\n")
        assert lines[0].startswith("[A] Abstract: Rapamycin was given")
        assert lines[1].startswith("[P1] (Results) Rapamycin reduced amyloid")
        assert pack.get("p1") is pack.passages[1] and pack.get("P99") is None

    def test_render_page_and_caption_labels(self) -> None:
        text = "Results\n\nTreated mice improved a lot in the maze test.\fFigure 3. Maze latency."
        rendered = render_pack(bm25_pack("maze latency", build_source_document(1, text)))
        assert "(Results, figure/table caption, p.2) Figure 3." in rendered


def _fake_embedder(calls: list[int], dims: int = 3):  # type: ignore[no-untyped-def]
    async def fake(texts: list[str], cost_tracker: object = None) -> list[list[float]]:
        calls.append(len(texts))
        return [[1.0, 0.0, 0.0][:dims] if "canine" in t or "dog" in t else [0.0, 1.0, 0.0][:dims]
                for t in texts]
    return fake


class TestHybrid:
    async def test_embedding_finds_semantic_match(
        self, doc: SourceDocument, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[int] = []
        monkeypatch.setattr(retrieval_embed, "embed_texts", _fake_embedder(calls))
        pack = await retrieve("dog", doc, max_tokens=600)
        assert pack.used_embeddings and "emb-rrf60" in pack.retrieval_version
        assert "canine cohort" in pack.passages[1].text

    async def test_document_vectors_cached(
        self, doc: SourceDocument, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[int] = []
        monkeypatch.setattr(retrieval_embed, "embed_texts", _fake_embedder(calls))
        await retrieve("dog", doc)
        await retrieve("mouse", doc)
        assert calls == [len(doc.windows), 1, 1]

    async def test_failure_falls_back_to_bm25(
        self, doc: SourceDocument, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def broken(texts: list[str], cost_tracker: object = None) -> list[list[float]]:
            raise RuntimeError("provider down")
        monkeypatch.setattr(retrieval_embed, "embed_texts", broken)
        pack = await retrieve("rapamycin amyloid", doc)
        assert not pack.used_embeddings and pack.retrieval_version.endswith(":bm25")
        assert len(pack.passages) > 1

    async def test_dimension_change_falls_back(
        self, doc: SourceDocument, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[int] = []
        monkeypatch.setattr(retrieval_embed, "embed_texts", _fake_embedder(calls))
        await retrieve("dog", doc)
        monkeypatch.setattr(retrieval_embed, "embed_texts", _fake_embedder(calls, dims=2))
        assert not (await retrieve("dog", doc)).used_embeddings


class TestCompatibilityNormalisation:
    """M9: query and source are NFKC-normalised the same way before BM25/embeddings."""

    def test_clean_query_folds_compatibility_characters(self) -> None:
        assert clean_query("Pores of 5 µm prevent hyperﬁbrosis (Smith et al., 2020).") \
            == "Pores of 5 μm prevent hyperfibrosis ."

    def test_ligature_pdf_text_is_retrieved_by_plain_claim(self) -> None:
        text = ("## Results\n\nMicrocapsules prevented hyperﬁbrosis around the graft. "
                "Oxygen diﬀusion limited islet survival.\n\n## Methods\n\n" + _FILLER)
        doc = build_source_document(1, text)
        assert "ﬁ" not in doc.full_text and "ﬀ" not in doc.full_text
        pack = bm25_pack("hyperfibrosis and oxygen diffusion limit islet grafts", doc)
        assert any("hyperfibrosis" in p.text for p in pack.passages)
