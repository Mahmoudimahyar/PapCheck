"""Bibliography & source issues and per-finding signals in the DOCX report (synthetic data).

Regression for the V4.9 review: duplicate entries (Wang 2024a = 2024b), citations
mapped to the wrong letter ("2024c" -> 2024a), a PDF of another year's report,
a scanned cover sheet and a Supporting-Information PDF all went unreported, and
each flagged citation printed the whole sentence and only the verifier's
verdict, although the reference was cited for one clause and the cross-check
had found support.
"""

from pathlib import Path

import docx

from refcheck.models.claim import Claim
from refcheck.models.evidence import ClaimLocation
from refcheck.models.pipeline import PipelineState
from refcheck.models.reference import ParsedManuscript, Reference
from refcheck.models.verification import ModelReasoning, VerificationResult
from refcheck.stages.generate_report import generate_report
from refcheck.stages.generate_report.claim_signals import (
    claim_signals,
    mapping_text,
    narrowed_cited_for,
)
from refcheck.stages.generate_report.source_issues import collect_source_issues
from refcheck.stages.generate_report.source_issues_section import SECTION_TITLE

_SENTENCE = "Gels lower IL-6 (Doe et al., 2018b) and degrade within weeks (Roe, 2020)."


def _claim(cid: int, ref: int, **extra: object) -> Claim:
    base: dict[str, object] = {
        "id": cid, "manuscript_text": _SENTENCE, "extracted_claim": _SENTENCE,
        "reference_ids": [ref], "cited_for": _SENTENCE,
        "location": ClaimLocation(paragraph_index=0, char_start=0, char_end=10,
                                  citation_markers=[f"(Ref{ref})"])}
    base.update(extra)
    return Claim.model_validate(base)


def _refs() -> list[Reference]:
    return [
        Reference(id=1, title="Wound gels A", doi="10.1/abc", year=2024, year_suffix="a"),
        Reference(id=2, title="Wound gels A", doi="https://doi.org/10.1/ABC", year=2024,
                  year_suffix="b", duplicate_of=1),
        Reference(id=3, title="Registry report", identity_status="mismatch"),
        Reference(id=4, title="Scanned paper"),
        Reference(id=5, title="Article with SI"),
        Reference(id=6, title="Record title from the DOI", repair_applied="title_from_api"),
        Reference(id=7, title="Withdrawn", retraction_status="retracted",
                  retraction_detail="Retraction notice 10.9/r"),
    ]


def _disputed(cid: int, ref: int) -> VerificationResult:
    return VerificationResult(
        claim_id=cid, reference_id=ref, verdict="partially_supported", confidence=0.6,
        consensus_type="disputed", needs_user_review=True, decided_by="verifier",
        layer_path=["verifier", "confirm"], reasoning="Shown as partial.",
        model_reasoning=[
            ModelReasoning(model_name="claude-haiku-5-5", model_display="Verifier · haiku",
                           verdict="not_supported", reasoning="Degradation time is absent."),
            ModelReasoning(model_name="gpt-6-luna", model_display="Confirm · luna",
                           verdict="partially_supported", reasoning="IL-6 drop is in P2.")])


def _verifications() -> list[VerificationResult]:
    return [
        _disputed(10, 1),
        VerificationResult(claim_id=11, reference_id=3, cannot_verify_reason="reference_mismatch"),
        VerificationResult(claim_id=12, reference_id=4, cannot_verify_reason="pdf_scanned"),
        VerificationResult(claim_id=13, reference_id=5, verdict="supported", reasoning=(
            "The attached PDF is the supplementary material, not the article; only the "
            "abstract was checked. Stated in the abstract.")),
        VerificationResult(claim_id=14, reference_id=4, verdict="not_supported", reasoning=(
            "Absent. Numbers not found in the source: 150 kPa — please check where they come "
            "from. Secondary citation: the source attributes this to other work — consider "
            "citing the primary study.")),
    ]


def _claims() -> list[Claim]:
    return [
        _claim(10, 1, cited_for="Gels lower IL-6", claim_quality="fragment"),
        _claim(11, 3), _claim(12, 4), _claim(13, 5), _claim(14, 4),
        _claim(15, 1, mapping_ambiguous=True, candidate_reference_ids=[1, 2]),
        _claim(16, 1, mapping_ambiguous=True, candidate_reference_ids=[1, 2]),
        _claim(17, 6, mapping_ambiguous=True, candidate_reference_ids=[6]),
    ]


class TestClaimSignals:
    def test_cited_for_only_when_narrower_than_the_sentence(self) -> None:
        assert narrowed_cited_for(_claim(1, 1)) == ""  # == extracted_claim: whole sentence
        assert narrowed_cited_for(_claim(1, 1, cited_for="")) == ""  # legacy row
        no_markers = _SENTENCE.replace(" (Doe et al., 2018b)", "").replace(" (Roe, 2020)", "")
        assert narrowed_cited_for(_claim(1, 1, cited_for=no_markers)) == ""
        spaced = _claim(1, 1, extracted_claim="Gels , made of X , lower IL-6.",
                        cited_for="Gels, made of X, lower IL-6")
        assert narrowed_cited_for(spaced) == ""
        assert narrowed_cited_for(_claim(1, 1, cited_for="Gels lower IL-6")) == \
            "Gels lower IL-6"

    def test_mapping_text_names_candidates_and_the_guess(self) -> None:
        text = mapping_text(_claim(1, 1, mapping_ambiguous=True,
                                   candidate_reference_ids=[1, 2, 9]))
        assert "“(Ref1)” could refer to [1], [2] or [9]" in text
        assert "checked against [1]" in text
        single = mapping_text(_claim(1, 6, mapping_ambiguous=True, candidate_reference_ids=[6]))
        assert "matches no reference by year" in single
        assert mapping_text(_claim(1, 1)) == "" and claim_signals(None).cited_for == ""


class TestCollect:
    def test_every_issue_kind_from_persisted_fields(self) -> None:
        issues = collect_source_issues(_refs(), _claims(), _verifications())
        by_kind = {i.kind: i for i in issues}
        assert set(by_kind) == {"retracted", "wrong_pdf", "scanned_pdf", "supplement_pdf",
                                "duplicate", "ambiguous_citation", "title_fixed"}
        assert by_kind["duplicate"].reference_ids == [1, 2]
        assert "same DOI" in by_kind["duplicate"].message
        assert by_kind["wrong_pdf"].reference_ids == [3] and by_kind["wrong_pdf"].claim_ids == [11]
        assert by_kind["scanned_pdf"].claim_ids == [12]  # claim 14's note is not a PDF problem
        assert by_kind["supplement_pdf"].claim_ids == [13]  # positive verdict, note only
        ambiguous = [i for i in issues if i.kind == "ambiguous_citation"]
        assert [(i.reference_ids, i.claim_ids) for i in ambiguous] == [([1, 2], [15, 16]),
                                                                      ([6], [17])]

    def test_identity_mismatch_without_verifications_is_reported(self) -> None:
        issues = collect_source_issues(_refs(), [], [])
        wrong = [i for i in issues if i.kind == "wrong_pdf"]
        assert len(wrong) == 1 and wrong[0].claim_ids == []

    def test_a_replaced_upload_stays_reported(self) -> None:
        ref = Reference(id=8, title="T", pdf_source="library", identity_status="verified",
                        replaced_upload_reason="identity_mismatch")
        issues = collect_source_issues([ref], [], [])
        assert [i.kind for i in issues] == ["replaced_pdf"]
        assert "a different paper" in issues[0].message and "library" in issues[0].message

    def test_no_issues_for_a_clean_bibliography(self) -> None:
        assert collect_source_issues([Reference(id=1, title="T")], [_claim(1, 1)],
                                     [VerificationResult(claim_id=1, reference_id=1)]) == []


def _report_text(tmp_path: Path, state: PipelineState) -> str:
    out = generate_report(state, tmp_path / "r.docx")
    return "\n".join(p.text for p in docx.Document(str(out)).paragraphs)


class TestReport:
    def _state(self) -> PipelineState:
        # No manuscript warnings: a regenerated report must rebuild duplicates from duplicate_of
        return PipelineState(session_id="s", manuscript=ParsedManuscript(filename="m.docx"),
                             references=_refs(), claims=_claims(),
                             verification_results=_verifications())

    def test_bibliography_section(self, tmp_path: Path) -> None:
        text = _report_text(tmp_path, self._state())
        assert SECTION_TITLE in text
        for heading in ("Duplicate reference (1)", "Attached PDF is a different paper (1)",
                        "Attached PDF is a scan without text (1)",
                        "Attached PDF is the supplement only (1)",
                        "In-text citation matches several references (2)",
                        "Garbled title replaced from the DOI/PMID record (1)"):
            assert heading in text
        assert "[2] repeats [1] (same DOI" in text and "Affected claims: 15, 16." in text
        assert "listed in their own section above" in text  # retraction keeps its section
        assert text.index("RETRACTED OR CORRECTED") < text.index(SECTION_TITLE)

    def test_finding_shows_cited_for_dispute_and_warnings(self, tmp_path: Path) -> None:
        text = _report_text(tmp_path, self._state())
        assert 'Cited for: "Gels lower IL-6"' in text
        assert "Warning: Claim text appears incomplete" in text
        assert "Disputed — the two models disagreed" in text
        assert "Verifier (claude-haiku-5-5): NOT SUPPORTED — Degradation time is absent." in text
        assert "Cross-check (gpt-6-luna): PARTIALLY SUPPORTED — IL-6 drop is in P2." in text
        assert "Numbers in the claim found nowhere in the source: 150 kPa" in text
        assert "Note: Secondary citation" in text
        assert "Disputed between the two models (both views shown below" in text

    def test_whole_sentence_claim_keeps_the_claim_line(self, tmp_path: Path) -> None:
        state = PipelineState(session_id="s", references=[Reference(id=1, title="T")],
                              claims=[_claim(1, 1)], verification_results=[
                                  VerificationResult(claim_id=1, reference_id=1,
                                                     verdict="not_supported")])
        text = _report_text(tmp_path, state)
        assert f"Claim: {_SENTENCE}" in text and "Cited for" not in text
        assert SECTION_TITLE not in text and "Disputed" not in text
