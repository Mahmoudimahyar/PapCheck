"""M11: sentence fragments cited as claims are flagged, not judged as claims.

Regression: "Combining these features (Kray et al., 2023)." was
verified as a claim and reported "not supported". It must carry
claim_quality="fragment" (still verified) so the report can say "Claim text
appears incomplete". All sentences are synthetic.
"""

import pytest

from refcheck.services.citation_converter import units_to_claims
from refcheck.stages.detect_citations.claim_quality import assess_claim_quality
from refcheck.stages.detect_citations.detector import detect_in_paragraph
from refcheck.stages.detect_citations.scope_resolver import resolve_scopes
from refcheck.stages.detect_citations.sentence_splitter import extract_sentence_context

_FRAGMENTS = [
    "Combining these features (Kray et al., 2023).",
    "Using alginate microcapsules to shield islets from antibodies (Lee et al., 2020).",
    "Combined with local tacrolimus release (Kim et al., 2019).",
    "pH-responsive micelles inside a gel matrix to carry siRNA to stem cells, the effects "
    "of serum on colloidal stability (Marsh et al., 2018).",
    "Adapted from Doe et al. (2018).",
    "Doe et al. (2002).",
    "2.3 Hydrogel Barrier Strategies (Smith et al., 2020)",
    "Hydrogel Barrier Strategies for Islets (Smith et al., 2020)",
]
_COMPLETE = [
    "Tacrolimus is nephrotoxic (Smith et al., 2020).",
    "Hydrogels reduce graft inflammation (Smith et al., 2020).",
    "The gel releases FK506 for weeks (Smith et al., 2020).",
    "Local delivery prolonged graft survival in rats (Smith et al., 2020).",
    "Hydrogels swell rapidly in serum (Smith et al., 2020).",
    "These include cell distribution and graft integration (Mann et al., 2016).",
    "Swelling and protein deposits contribute to tissue sticking (Hart et al., 2023).",
    "Doe et al. (2020) used PEG tubes to protect spinal progenitors.",
    "Calcineurin inhibitors pose systemic toxicities (Mills et al., 2019).",
    "Combining gels with drugs improves graft survival (Lee et al., 2021).",
]


class TestAssessClaimQuality:
    @pytest.mark.parametrize("sentence", _FRAGMENTS)
    def test_fragments_are_flagged(self, sentence: str) -> None:
        assert assess_claim_quality(sentence) == "fragment"

    @pytest.mark.parametrize("sentence", _COMPLETE)
    def test_complete_claims_are_ok(self, sentence: str) -> None:
        assert assess_claim_quality(sentence) == "ok"


class TestPipelineCarriesQuality:
    def test_fragment_flag_reaches_claim_and_is_still_verified(self) -> None:
        text = ("Hydrogels reduce fibrosis (Smith et al., 2020). "
                "Combining these features (Kray et al., 2023).")
        cits = detect_in_paragraph(text, 0, "Introduction")
        mapped = [c.model_copy(update={"reference_id": i}) for i, c in enumerate(cits, 1)]
        claims = units_to_claims(resolve_scopes(mapped))
        assert [c.claim_quality for c in claims] == ["ok", "fragment"]
        assert len(claims) == 2  # fragments are flagged, not dropped


class TestSentenceBoundariesBehindFragments:
    def test_lowercase_term_starts_a_new_sentence(self) -> None:
        """"... (Dove et al., 2025).  pH-responsive ..." used to merge two claims."""
        text = ("Gels protect genes from nucleases (Dove et al., 2025).  pH-responsive "
                "micelles carry siRNA into stem cells (Marsh et al., 2018).")
        start = text.index("(Marsh")
        sentence, _, _ = extract_sentence_context(text, start, start + 5)
        assert sentence.startswith("pH-responsive")

    def test_et_al_with_narrow_no_break_space(self) -> None:
        """"Mazur et al. (2020) did X" was cut after "al." into a fragment."""
        text = "To fix this, Doe et al. (2020) loaded a gel with drug. Next sentence here."
        start = text.index("(2020)")
        sentence, _, _ = extract_sentence_context(text, start, start + 6)
        assert sentence.startswith("To fix this") and sentence.endswith("with drug.")

    def test_word_ending_like_an_abbreviation_still_ends_a_sentence(self) -> None:
        """"systems." / "platforms." were protected as "Ms." and merged sentences."""
        text = "Depots lack feedback systems. Smart gels respond to enzymes (Lee et al., 2019)."
        start = text.index("(Lee")
        sentence, _, _ = extract_sentence_context(text, start, start + 4)
        assert sentence.startswith("Smart gels")
