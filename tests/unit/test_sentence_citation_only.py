"""Citation-only fragments after a sentence-final period belong to that sentence."""

from refcheck.stages.detect_citations.detector import detect_in_paragraph
from refcheck.stages.detect_citations.sentence_splitter import (
    extract_sentence_context,
)


class TestCitationOnlyFragments:
    def test_trailing_author_year_group_joins_previous_sentence(self) -> None:
        text = (
            "Hydrogels reduce local inflammation after grafting. "
            "(Wade et al., 2020; Bento et al., 2025). Other work differs."
        )
        pos = text.index("(Wade")
        sent, _, _ = extract_sentence_context(text, pos, pos + 10)
        assert sent.startswith("Hydrogels reduce local inflammation")
        assert "(Wade et al., 2020; Bento et al., 2025)" in sent
        assert "Other work" not in sent

    def test_trailing_numbered_citation_joins_previous_sentence(self) -> None:
        text = "Islet survival improved with encapsulation. [12, 13]. Next."
        pos = text.index("[12")
        sent, _, _ = extract_sentence_context(text, pos, pos + 3)
        assert sent.startswith("Islet survival improved")

    def test_normal_sentences_are_not_merged(self) -> None:
        text = "First sentence is long enough. Second sentence (Lee, 2019) too."
        pos = text.index("(Lee")
        sent, _, _ = extract_sentence_context(text, pos, pos + 5)
        assert sent.startswith("Second sentence")

    def test_detector_scope_is_not_empty(self) -> None:
        text = (
            "Local tacrolimus delivery prolonged allograft survival in rats. "
            "(Mills et al., 2019; Mazur et al., 2020)."
        )
        cits = detect_in_paragraph(text, 0, "Results")
        assert cits
        assert all("tacrolimus" in c.sentence_text for c in cits)
