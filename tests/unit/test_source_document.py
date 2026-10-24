"""Tests for source documents: sanitizing, sections, back-matter removal, loading."""

from pathlib import Path

import fitz

from refcheck.models.reference import Reference
from refcheck.stages.verify_claims.source_document import (
    build_source_document,
    load_pdf_document,
    load_source_document,
)

_ABSTRACT = (
    "Reduced TOR signaling increases lifespan in many organisms. Rapamycin inhibits the "
    "mTOR pathway in mice. We asked whether rapamycin prevents cognitive decline. "
)
MARKDOWN = (
    "# Rapamycin and Alzheimer models\n\n## Abstract\n\n### Background\n\n" + _ABSTRACT
    + "\n\n### Methods\n\nWe treated PDAPP mice with rapamycin for thirteen weeks. "
    "Cognition was tested in the Morris water maze.\n\n"
    "## Introduction\n\nAlzheimer's disease is the most common neurodegenerative disorder. "
    "Amyloid accumulation is a hallmark of the disease. Autophagy clears protein aggregates.\n\n"
    "## Results\n\nRapamycin lowered amyloid levels by 40% in treated mice (Fig. 2). "
    "Autophagy was increased in neurons of treated animals. Memory improved in the water maze. "
    "Control animals showed no change in amyloid levels.\n\n"
    "Figure 2. Amyloid levels in treated and control mice after thirteen weeks.\n\n"
    "## Acknowledgments\n\nWe thank the funding agency for generous support.\n\n"
    "## References\n\n  * Smith J, Jones K. A paper about mice. Nature. 2009;461:495-500.\n"
)


def _texts(doc_chunks: list[object]) -> str:
    return " ".join(str(getattr(c, "text", "")) for c in doc_chunks)


class TestBuildFromMarkdown:
    def test_abstract_unit_first_with_structured_parts(self) -> None:
        doc = build_source_document(1, MARKDOWN)
        assert doc.has_abstract_chunk and doc.abstract_source == "document"
        abstract = doc.chunks[0]
        assert abstract.kind == "abstract" and abstract.idx == 0
        assert "Reduced TOR signaling" in abstract.text
        assert "Morris water maze" in abstract.text  # "### Methods" stays in the abstract

    def test_back_matter_dropped(self) -> None:
        doc = build_source_document(1, MARKDOWN)
        everything = _texts(doc.chunks) + doc.full_text
        assert "We thank" not in everything
        assert "Smith J" not in everything

    def test_sections_and_captions(self) -> None:
        doc = build_source_document(1, MARKDOWN)
        results = [c for c in doc.windows if c.heading == "Results" and c.kind == "window"]
        assert results and "lowered amyloid levels by 40%" in results[0].text
        captions = [c for c in doc.windows if c.kind == "caption"]
        assert len(captions) == 1 and captions[0].text.startswith("Figure 2.")
        assert any(c.heading == "Introduction" for c in doc.windows)

    def test_windows_are_three_sentences_stride_two(self) -> None:
        doc = build_source_document(1, MARKDOWN)
        results = [c for c in doc.windows if c.heading == "Results" and c.kind == "window"]
        assert [(c.sent_end - c.sent_start) for c in results] == [3, 2]
        assert results[1].sent_start == results[0].sent_start + 2

    def test_metadata_abstract_wins(self) -> None:
        meta = "PubMed abstract text about rapamycin and amyloid in mice. " * 4
        doc = build_source_document(1, MARKDOWN, abstract_text=meta)
        assert doc.abstract_source == "reference"
        assert doc.chunks[0].text.startswith("PubMed abstract text")

    def test_fingerprint_stable_and_content_sensitive(self) -> None:
        a = build_source_document(1, MARKDOWN)
        b = build_source_document(2, MARKDOWN)
        c = build_source_document(1, MARKDOWN.replace("40%", "45%"))
        assert a.fingerprint == b.fingerprint != c.fingerprint


def _body(n: int, topic: str) -> str:
    return " ".join(f"Sentence {i} reports {topic} findings in detail." for i in range(n))


class TestPdfStyleText:
    def test_pages_and_unlabelled_abstract(self) -> None:
        text = (
            "A study title\n\nAuthor One, Author Two\n\n" + _body(12, "abstract") + "\n\n"
            "KEYWORDS\n\n1 Introduction\n\n" + _body(6, "intro") + "\f2 Results\n\n"
            + _body(6, "result")
        )
        doc = build_source_document(3, text)
        assert doc.abstract_chunk is not None and "abstract findings" in doc.abstract_chunk.text
        pages = {c.heading: c.page for c in doc.windows}
        assert pages["Introduction"] == 1 and pages["Results"] == 2

    def test_early_references_table_header_does_not_drop_body(self) -> None:
        blocks = ["Introduction", _body(4, "intro"), "References", "(11, 13)", "(14)"]
        blocks += [_body(3, f"body{i}") for i in range(20)]
        doc = build_source_document(4, "\n\n".join(blocks))
        assert "body19 findings" in doc.full_text

    def test_reference_list_dropped_when_entries_follow(self) -> None:
        blocks = ["Introduction"] + [_body(3, f"body{i}") for i in range(8)]
        blocks += ["References", "1. Smith J, Jones K. Mice. Nature. 2009;461:495.",
                   "2. Doe A. Rats. Cell. 2011;12:1-9."]
        doc = build_source_document(5, "\n\n".join(blocks))
        assert "Smith J" not in doc.full_text and "body7 findings" in doc.full_text

    def test_ligatures_and_hyphenation_cleaned(self) -> None:
        text = "Introduction\n\nThe eﬃcacy of the aggre-\ngation inhibitor was signiﬁcant here."
        doc = build_source_document(6, text)
        assert "efficacy" in doc.full_text and "aggregation" in doc.full_text
        assert "significant" in doc.full_text


def _make_pdf(path: Path, pages: list[list[str]]) -> Path:
    doc = fitz.open()
    for blocks in pages:
        page = doc.new_page()
        y = 60.0
        for block in blocks:
            height = 14.0 * (len(block) // 80 + 2)
            page.insert_textbox(fitz.Rect(60, y, 540, y + height), block, fontsize=9)
            y += height + 16
    doc.save(str(path))
    doc.close()
    return path


class TestLoadSourceDocument:
    def test_pdf_document_with_pages_and_cache(self, tmp_path: Path) -> None:
        pdf = _make_pdf(tmp_path / "a.pdf", [
            ["Abstract", _body(8, "abstract"), "Introduction", _body(4, "intro")],
            ["Results", _body(6, "result"), "Discussion", _body(4, "discussion")],
        ])
        doc = load_pdf_document(pdf, ref_id=9)
        assert doc.coverage == "full_text" and doc.n_pages == 2
        assert {c.page for c in doc.windows if c.heading == "Results"} == {2}
        assert load_pdf_document(pdf, ref_id=9) is doc  # cached per file version

    def test_abstract_only_reference(self) -> None:
        ref = Reference(id=2, abstract_text="An abstract about rapamycin in mice. " * 5)
        doc = load_source_document(ref)
        assert doc is not None and doc.coverage == "abstract_only"
        assert [c.kind for c in doc.chunks] == ["abstract"]

    def test_no_source_returns_none(self) -> None:
        assert load_source_document(Reference(id=3)) is None

    def test_unreadable_pdf_falls_back_to_abstract(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.pdf"
        bad.write_bytes(b"not a pdf")
        ref = Reference(id=4, pdf_path=bad, abstract_text="Abstract words for a fallback. " * 5)
        doc = load_source_document(ref)
        assert doc is not None and doc.coverage == "abstract_only"
        assert doc.quality_reason == "pdf_unreadable"

    def test_unreadable_pdf_without_abstract_reports_quality(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.pdf"
        bad.write_bytes(b"not a pdf")
        doc = load_source_document(Reference(id=5, pdf_path=bad))
        assert doc is not None and not doc.chunks
        assert doc.quality_reason == "pdf_unreadable" and doc.quality_score == 0.0
