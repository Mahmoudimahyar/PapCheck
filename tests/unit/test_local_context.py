"""Paragraph window for citations: local paragraph, never the whole section."""

from refcheck.models.citation import CitationInstance
from refcheck.models.reference import ManuscriptSection, ParsedManuscript
from refcheck.stages.detect_citations import detect_all_citations
from refcheck.stages.detect_citations.detector import detect_in_paragraph
from refcheck.stages.detect_citations.local_context import (
    PARAGRAPH_WINDOW_CHARS,
    add_context,
    clip_sentence_to_line,
    line_span,
    local_paragraph,
)

# The DOCX parser joins Word paragraphs with a single newline.
_SECTION = "\n".join([
    "Bone defects remain a major clinical problem in orthopaedics.",
    "Hydrogels are widely used in tissue engineering (Smith et al., 2020). "
    "They can be tuned for stiffness.",
    "Unrelated third paragraph about funding and ethics approval.",
])


class TestLineSpan:
    def test_middle_line(self) -> None:
        text = "aaa\nbbb\nccc"
        assert line_span(text, 5) == (4, 7)

    def test_last_line_and_bounds(self) -> None:
        text = "aaa\nbbb"
        assert line_span(text, 6) == (4, 7)
        assert line_span(text, 99) == (4, 7)
        assert line_span(text, -5) == (0, 3)


class TestLocalParagraph:
    def test_returns_only_the_containing_line(self) -> None:
        start = _SECTION.index("Hydrogels")
        end = _SECTION.index("(Smith et al., 2020).") + 21
        para = local_paragraph(_SECTION, start, end)
        assert para.startswith("Hydrogels are widely used")
        assert "tuned for stiffness" in para
        assert "Bone defects" not in para
        assert "funding" not in para

    def test_long_paragraph_is_capped_around_sentence(self) -> None:
        filler = "word " * 1500  # 7,500 chars on one line
        sentence = "Scaffold porosity drives vascularisation [12]."
        text = filler + sentence + " " + filler
        start = text.index(sentence)
        para = local_paragraph(text, start, start + len(sentence))
        assert len(para) <= PARAGRAPH_WINDOW_CHARS
        assert sentence in para
        # centred: there is context on both sides of the sentence
        assert para.index(sentence) > 500
        assert len(para) - para.index(sentence) - len(sentence) > 500

    def test_window_never_cuts_words(self) -> None:
        text = ("alpha beta gamma delta " * 200) + "Target sentence [1]." + (" omega" * 400)
        start = text.index("Target")
        para = local_paragraph(text, start, start + 20, max_chars=300)
        assert para.split()[0] in {"alpha", "beta", "gamma", "delta"}
        assert para.split()[-1] in {"omega", "[1].", "sentence"}

    def test_empty_text(self) -> None:
        assert local_paragraph("", 0, 0) == ""


class TestClipSentence:
    def test_clips_sentence_running_over_paragraph_break(self) -> None:
        text = "Background\nHydrogels are useful (Smith, 2020)."
        anchor = text.index("(Smith")
        sentence, start, _end = clip_sentence_to_line(text, 0, len(text), anchor)
        assert sentence == "Hydrogels are useful (Smith, 2020)."
        assert start == text.index("Hydrogels")


class TestDetectorUsesLocalParagraph:
    def test_detect_all_citations_paragraph_is_local(self) -> None:
        ms = ParsedManuscript(
            filename="t.docx",
            sections=[ManuscriptSection(heading="Introduction", text=_SECTION)],
        )
        cits = detect_all_citations(ms)
        assert len(cits) == 1
        cit = cits[0]
        assert cit.paragraph_text.startswith("Hydrogels are widely used")
        assert "Bone defects" not in cit.paragraph_text
        assert "funding" not in cit.paragraph_text
        assert cit.sentence_text.startswith("Hydrogels are widely used")

    def test_whole_section_never_used_for_long_sections(self) -> None:
        paragraphs = [f"Paragraph {i} says something about cells." for i in range(300)]
        paragraphs[150] = "Stem cells differentiate under load (Lee et al., 2019)."
        ms = ParsedManuscript(
            filename="t.docx",
            sections=[ManuscriptSection(heading="Intro", text="\n".join(paragraphs))],
        )
        cit = detect_all_citations(ms)[0]
        assert cit.paragraph_text == paragraphs[150]

    def test_detect_in_paragraph_single_line_unchanged(self) -> None:
        text = "Drug X is effective (Smith et al., 2020)."
        cits = detect_in_paragraph(text, para_idx=0, section="Intro")
        assert cits and cits[0].paragraph_text == text

    def test_add_context_sets_all_fields(self) -> None:
        start = _SECTION.index("(Smith")
        cit = CitationInstance(
            raw_marker="(Smith et al., 2020)", style="author_year_parenthetical",
            paragraph_index=0, char_start=start, char_end=start + 20,
        )
        out = add_context(cit, _SECTION)
        assert out.sentence_text.endswith("(Smith et al., 2020).")
        assert out.sentence_start == _SECTION.index("Hydrogels")
        assert "Bone defects" not in out.paragraph_text
