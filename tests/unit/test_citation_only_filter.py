"""Citation-only predicates, the subject-less verb opener, and skipping a
citing sentence that is still only a citation (nothing to attach it to)."""

import pytest

from refcheck.models.claim import Claim
from refcheck.services.citation_converter import units_to_claims
from refcheck.stages.detect_citations.citation_only import (
    is_citation_only,
    is_narrative_only,
)
from refcheck.stages.detect_citations.claim_filter import filter_empty_claims
from refcheck.stages.detect_citations.detector import detect_in_paragraph
from refcheck.stages.detect_citations.scope_resolver import resolve_scopes
from refcheck.stages.detect_citations.verb_heuristics import opens_with_predicate


class TestIsCitationOnly:
    @pytest.mark.parametrize("text", [
        "Lee et al. (2002).",
        "Lee et al† (2002).",  # splitter placeholder for the dot
        "Lee and Kim (2010a, 2011).",
        "Lee & Kim (2010); Park (2012).",
        "(Lee et al., 2020; Kim, 2021).",
        "[3, 5-7].",
        "See also Lee et al. (2002).",
    ])
    def test_citation_only(self, text: str) -> None:
        assert is_citation_only(text)

    @pytest.mark.parametrize("text", [
        "Lee et al. (2002) used agent Q in mice.",
        "Hydrogels help healing (Lee, 2020).",
        "Adapted from Lee et al. (2002).",
        "Lee et al. (2002) 45%.",
        "No markers at all.",
        "",
    ])
    def test_not_citation_only(self, text: str) -> None:
        assert not is_citation_only(text)

    def test_narrative_only_needs_a_narrative_marker(self) -> None:
        assert is_narrative_only("Lee et al. (2002).")
        assert not is_narrative_only("(Lee et al., 2002).")


class TestOpensWithPredicate:
    @pytest.mark.parametrize("text", [
        "Used agent Q in mice to raise fiber counts.",
        "Applied systemic agent Q with grafts.",
        "Showed that agent Q shortened healing.",
        "Also reported a drop in rejection.",
        "Demonstrates a dose effect in rats.",
    ])
    def test_subjectless_verb(self, text: str) -> None:
        assert opens_with_predicate(text)

    @pytest.mark.parametrize("text", [
        "The hydrogel released the drug.",
        "Based on these data, the authors proposed local delivery.",
        "Compared with controls, fiber counts rose.",
        "Limited data suggest a similar effect.",
        "Increased levels were seen in mice.",
        "Reports suggest a benefit.",
        "Need for repeated dosing remains.",
        "Used.",
        "",
    ])
    def test_not_subjectless_verb(self, text: str) -> None:
        assert not opens_with_predicate(text)


def _claim(text: str, extracted: str) -> Claim:
    return Claim(id=1, manuscript_text=text, extracted_claim=extracted, reference_ids=[7])


class TestFilterSkipsCitationOnly:
    def test_narrative_citation_only_sentence_is_skipped(self) -> None:
        # The narrative scope fallback leaves the author name ("Lee et al").
        assert filter_empty_claims([_claim("Lee et al. (2002).", "Lee et al")]) == []

    def test_real_narrative_claim_is_kept(self) -> None:
        claim = _claim("Lee et al. (2002) used agent Q in mice.", "used agent Q in mice.")
        assert filter_empty_claims([claim]) == [claim]

    def test_fragment_with_nothing_to_attach_to_never_reaches_verification(self) -> None:
        # Starts its paragraph and the next sentence has its own subject.
        text = "Lee et al. (2002). The hydrogel released the drug for weeks."
        cits = [
            c.model_copy(update={"reference_id": 7})
            for c in detect_in_paragraph(text, 0, "R")
        ]
        assert [c.sentence_text for c in cits] == ["Lee et al. (2002)."]
        assert filter_empty_claims(units_to_claims(resolve_scopes(cits))) == []

    def test_merged_fragment_stays_verifiable(self) -> None:
        text = "Agent Q was tested first. Lee et al. (2002). Used agent Q in mice to cut rejection."
        cits = [
            c.model_copy(update={"reference_id": 7})
            for c in detect_in_paragraph(text, 0, "R")
        ]
        claims = filter_empty_claims(units_to_claims(resolve_scopes(cits)))
        assert len(claims) == 1
        assert "Used agent Q" in claims[0].manuscript_text
