"""Tests for text quality scoring and coherence checking integration."""


from refcheck.stages.verify_claims.text_quality import (
    check_topic_coherence,
    score_pdf_text,
)


class TestScorePdfText:
    """Tests for the PDF text quality scorer."""

    def test_metadata_only_returns_low_score(self) -> None:
        """Text under 500 chars should be flagged as metadata-only."""
        result = score_pdf_text("Short text only")
        assert result["is_metadata_only"] is True
        assert result["score"] == 0.1

    def test_long_text_with_sections_scores_high(self) -> None:
        """Full paper text with abstract/results should score 1.0."""
        text = (
            "Abstract\n" + "word " * 100
            + "\nResults\n" + "word " * 100
        )
        result = score_pdf_text(text)
        assert result["score"] == 1.0
        assert result["has_abstract"] is True
        assert result["has_results"] is True

    def test_medium_text_without_sections(self) -> None:
        """Text with 200+ words but no section keywords scores 0.6."""
        text = "content " * 250
        result = score_pdf_text(text)
        assert result["score"] == 0.6
        assert result["has_abstract"] is False

    def test_supplement_detected(self) -> None:
        """Supplementary materials flagged with low score."""
        text = "Supplementary Table S1\n" + "data " * 200
        result = score_pdf_text(text)
        assert result["is_likely_supplement"] is True
        assert result["score"] == 0.2

    def test_short_but_real_text(self) -> None:
        """Text 500-800 chars (under 200 words) gets 0.4."""
        text = "meaningful " * 60  # ~660 chars, ~60 words
        result = score_pdf_text(text)
        assert result["score"] == 0.4
        assert result["is_metadata_only"] is False

    def test_empty_text(self) -> None:
        result = score_pdf_text("")
        assert result["score"] == 0.1
        assert result["is_metadata_only"] is True


class TestCheckTopicCoherence:
    """Tests for keyword overlap coherence checker."""

    def test_high_coherence(self) -> None:
        """Claim and section sharing many keywords → high score."""
        claim = "hydrogel scaffolds promote bone tissue regeneration"
        section = (
            "In this study, hydrogel scaffolds were fabricated for bone "
            "tissue engineering and showed excellent regeneration capacity."
        )
        score = check_topic_coherence(claim, section)
        assert score >= 0.3

    def test_low_coherence(self) -> None:
        """Completely unrelated topics → near zero."""
        claim = "immune response in cancer patients"
        section = "quantum computing algorithms for optimization problems"
        score = check_topic_coherence(claim, section)
        assert score < 0.10

    def test_empty_claim(self) -> None:
        score = check_topic_coherence("", "some section text here")
        assert score == 0.0

    def test_empty_section(self) -> None:
        score = check_topic_coherence("real claim text", "")
        assert score == 0.0

    def test_stopwords_excluded(self) -> None:
        """Stopwords like 'the', 'is' should not inflate score."""
        claim = "the is a an for to"
        section = "the is a an for to in on at"
        score = check_topic_coherence(claim, section)
        assert score == 0.0

    def test_partial_overlap(self) -> None:
        """Partial keyword overlap gives moderate score."""
        claim = "bone scaffold implant design optimization"
        section = "scaffold design fabrication using 3D printing polymer"
        score = check_topic_coherence(claim, section)
        assert 0.1 < score < 0.8
