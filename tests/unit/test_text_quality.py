"""Tests for PDF text quality scoring and topic coherence (V2)."""

from refcheck.stages.verify_claims.text_quality import (
    check_topic_coherence,
    score_pdf_text,
)


def test_normal_paper_high_score() -> None:
    """Normal paper text gets score > 0.6."""
    text = (
        "Abstract\n\nThis study examined hydrogel-based approaches "
        "for organ transplantation. "
        + "Methods\n\nWe conducted a randomized trial. " * 50
        + "Results\n\nThe hydrogel group showed significant improvement."
    )
    result = score_pdf_text(text)
    assert result["score"] > 0.6
    assert result["has_abstract"] is True
    assert result["has_methods"] is True
    assert result["has_results"] is True
    assert result["is_metadata_only"] is False


def test_metadata_only_low_score() -> None:
    """Metadata-only text (< 500 chars) gets score ≈ 0.1."""
    text = "Title: Some Paper\nAuthors: Smith, Jones\nDOI: 10.1234/test"
    result = score_pdf_text(text)
    assert result["score"] <= 0.15
    assert result["is_metadata_only"] is True


def test_supplement_text_low_score() -> None:
    """Supplement text gets score ≈ 0.2."""
    text = (
        "Supplementary Materials\nTable S1: Extended data\n"
        + "Data values " * 200
    )
    result = score_pdf_text(text)
    assert result["score"] <= 0.25
    assert result["is_likely_supplement"] is True


def test_short_text_medium_score() -> None:
    """Short text (< 200 words) gets score 0.4."""
    text = "Some content here. " * 10  # ~40 words
    result = score_pdf_text(text)
    assert result["score"] <= 0.5


def test_text_without_sections_medium_score() -> None:
    """Text with no abstract/results gets 0.6."""
    text = "Some general discussion about the topic. " * 100
    result = score_pdf_text(text)
    assert result["score"] <= 0.65
    assert result["has_abstract"] is False
    assert result["has_results"] is False


def test_coherence_related_claim_section() -> None:
    """Related claim and section have coherence > 0.10."""
    claim = "Hydrogel scaffolds improved cell viability in transplantation"
    section = (
        "Our hydrogel-based scaffold significantly enhanced cell viability "
        "when used in organ transplantation models."
    )
    score = check_topic_coherence(claim, section)
    assert score > 0.10


def test_coherence_unrelated_claim_section() -> None:
    """Unrelated claim and section have low coherence."""
    claim = "Hydrogel scaffolds improved cell viability in transplantation"
    section = (
        "The stock market experienced significant volatility due to "
        "changes in monetary policy and interest rate adjustments."
    )
    score = check_topic_coherence(claim, section)
    assert score < 0.10


def test_coherence_empty_text() -> None:
    """Empty claim text returns 0.0."""
    score = check_topic_coherence("", "Some text here")
    assert score == 0.0


def test_main_paper_mentioning_supplement_not_flagged() -> None:
    """V5: 'Supplementary Table S1' inside the abstract is not a supplement title."""
    text = (
        "Rapamycin prevents cognitive deficits in mice\n"
        "Abstract\nWe treated mice with rapamycin (Supplementary Table S1 lists doses) "
        "and supporting information is online.\n" + "Results were robust. " * 100
    )
    result = score_pdf_text(text)
    assert result["is_likely_supplement"] is False
    assert result["score"] == 1.0


def test_supplement_heading_in_title_area_flagged() -> None:
    """V5: supplement headings (incl. SDC) in the first lines are detected."""
    for title in ("Supporting Information", "SDC, Materials and Methods", "Figure S1"):
        text = f"{title}\nfor: A study of mice\n" + "data values " * 200
        assert score_pdf_text(text)["is_likely_supplement"] is True, title


def test_supplement_heading_after_title_area_ignored() -> None:
    lines = "\n".join(f"Line {i} of the main paper text." for i in range(12))
    text = lines + "\nSupplementary Materials\n" + "Results abstract words. " * 100
    assert score_pdf_text(text)["is_likely_supplement"] is False


def test_describe_quality_reasons() -> None:
    from refcheck.stages.verify_claims.text_quality import describe_quality

    assert describe_quality("tiny")[1] == "metadata_only"
    assert describe_quality("Supplementary Materials\n" + "data " * 300)[1] == "likely_supplement"
    assert describe_quality("Abstract\n" + "word " * 300) == (1.0, "ok")
