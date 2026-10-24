"""Tests for scope resolution."""

from refcheck.models.citation import CitationInstance
from refcheck.stages.detect_citations.scope_resolver import (
    classify_claim_type,
    resolve_scopes,
)


def _make_cit(
    sentence: str, raw: str, is_narrative: bool = False,
    para: int = 0, ref_id: int = 1,
    char_start: int = 0, char_end: int = 10,
) -> CitationInstance:
    return CitationInstance(
        raw_marker=raw,
        style="author_year_narrative" if is_narrative else "author_year_parenthetical",
        paragraph_index=para,
        char_start=char_start,
        char_end=char_end,
        section_heading="Results",
        sentence_text=sentence,
        sentence_start=0,
        sentence_end=len(sentence),
        is_narrative=is_narrative,
        reference_id=ref_id,
        authors=["Smith"],
        year="2020",
    )


class TestScopeResolver:
    def test_single_citation_full_scope(self) -> None:
        cit = _make_cit(
            "Hydrogels are biocompatible (Smith et al., 2020).",
            "(Smith et al., 2020)",
        )
        units = resolve_scopes([cit])
        assert len(units) == 1
        assert "biocompatible" in units[0].scope_text
        # Should NOT contain the citation marker
        assert "(Smith" not in units[0].scope_text

    def test_compound_shared_scope(self) -> None:
        sent = "Hydrogels are useful (Smith, 2020; Jones, 2021)."
        c1 = _make_cit(sent, "(Smith, 2020)", ref_id=1)
        c2 = _make_cit(sent, "(Jones, 2021)", ref_id=2)
        units = resolve_scopes([c1, c2])
        assert len(units) == 2
        # Both should have similar scope
        assert "useful" in units[0].scope_text
        assert "useful" in units[1].scope_text

    def test_narrative_at_start(self) -> None:
        cit = _make_cit(
            "Smith et al. (2020) developed a novel hydrogel.",
            "Smith et al. (2020)",
            is_narrative=True,
        )
        units = resolve_scopes([cit])
        assert len(units) == 1
        assert "developed" in units[0].scope_text

    def test_claim_type_factual_percentage(self) -> None:
        ct, prio = classify_claim_type("survival rate was 30%", False)
        assert ct == "factual"
        assert prio == "high"

    def test_claim_type_attribution_narrative(self) -> None:
        ct, prio = classify_claim_type("developed a new method", True)
        assert ct == "attribution"
        assert prio == "medium"

    def test_claim_type_contrast(self) -> None:
        ct, prio = classify_claim_type("unlike previous methods", False)
        assert ct == "contrast"
        assert prio == "high"

    def test_claim_type_background(self) -> None:
        ct, prio = classify_claim_type("X is known to cause Y", False)
        assert ct == "background"
        assert prio == "low"


class TestCoCitedCount:
    def test_single_citation_counts_one(self) -> None:
        cit = _make_cit("Hydrogels are useful (Smith, 2020).", "(Smith, 2020)")
        assert resolve_scopes([cit])[0].co_cited_count == 1

    def test_three_references_in_one_sentence(self) -> None:
        sent = "Hydrogels are useful (Smith, 2020; Jones, 2021; Lee, 2022)."
        cits = [
            _make_cit(sent, "(Smith, 2020)", ref_id=1),
            _make_cit(sent, "(Jones, 2021)", ref_id=2),
            _make_cit(sent, "(Lee, 2022)", ref_id=3),
        ]
        units = resolve_scopes(cits)
        assert [u.co_cited_count for u in units] == [3, 3, 3]

    def test_duplicate_reference_counted_once(self) -> None:
        sent = "Hydrogels are useful [1, 1]."
        cits = [_make_cit(sent, "[1]", ref_id=1), _make_cit(sent, "[1]", ref_id=1)]
        assert all(u.co_cited_count == 1 for u in resolve_scopes(cits))

    def test_other_sentence_not_counted(self) -> None:
        c1 = _make_cit("First claim here (Smith, 2020).", "(Smith, 2020)", ref_id=1)
        c2 = _make_cit("Second claim (Jones, 2021).", "(Jones, 2021)", para=1, ref_id=2)
        assert [u.co_cited_count for u in resolve_scopes([c1, c2])] == [1, 1]

    def test_propagates_to_claim(self) -> None:
        from refcheck.services.citation_converter import units_to_claims

        sent = "Hydrogels are useful (Smith, 2020; Jones, 2021)."
        units = resolve_scopes([
            _make_cit(sent, "(Smith, 2020)", ref_id=1),
            _make_cit(sent, "(Jones, 2021)", ref_id=2),
        ])
        claims = units_to_claims(units)
        assert [c.co_cited_count for c in claims] == [2, 2]


class TestKeywordWordBoundaries:
    def test_is_a_inside_other_words_is_not_background(self) -> None:
        # "this approach" contains the substring "is a"
        ct, _ = classify_claim_type("cartilage repair with this agent", False)
        assert ct == "factual"

    def test_is_a_phrase_still_background(self) -> None:
        ct, prio = classify_claim_type("osteoarthritis is a degenerative disease", False)
        assert (ct, prio) == ("background", "low")

    def test_using_inside_focusing_is_not_methodological(self) -> None:
        ct, _ = classify_claim_type("refocusing of the beam improves imaging", False)
        assert ct == "factual"

    def test_inflected_method_word_still_matches(self) -> None:
        ct, _ = classify_claim_type("samples were assessed with standard methods", False)
        assert ct == "methodological"
