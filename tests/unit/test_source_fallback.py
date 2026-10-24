"""M6/M14: a wrong or unusable PDF yields a reasoned cannot_verify, never not_supported."""

import asyncio
from pathlib import Path

import fitz
import pytest

from refcheck.models.cannot_verify import CannotVerifyReason, classify_quality_reason
from refcheck.models.reference import Reference
from refcheck.models.verification import VerificationResult
from refcheck.stages.verify_claims import source_resolve
from refcheck.stages.verify_claims.source_document import (
    build_abstract_document,
    build_source_document,
)
from refcheck.stages.verify_claims.source_fallback import (
    annotate_source_fallback,
    fallback_reason,
    judgeable_abstract,
    mismatch_abstract_document,
)
from refcheck.stages.verify_claims.source_models import QualityReason
from refcheck.stages.verify_claims.verifier_helpers import resolve_source

_ABSTRACT = ("In this registry report, heart transplant volumes increased and acute rejection "
             "within the first year declined among adult recipients transplanted in the most "
             "recent cohort compared with earlier cohorts of recipients. Graft survival at five "
             "years improved in every age group, and waiting-list mortality fell in the most "
             "recent era.")


def _ref(**kw: object) -> Reference:
    base: dict[str, object] = {"id": 22, "title": "Registry 2017 Annual Data Report",
                               "abstract_text": _ABSTRACT, "abstract_source": "semantic_scholar",
                               "identity_status": "mismatch", "source_status": "found"}
    base.update(kw)
    return Reference.model_validate(base)


def _result(verdict: str, reason: str | None = None) -> VerificationResult:
    return VerificationResult(claim_id=1, reference_id=22, verdict=verdict,  # type: ignore[arg-type]
                              confidence=0.8, reasoning="Model explanation.",
                              cannot_verify_reason=reason)


class TestMismatchSource:
    def test_api_abstract_is_used_and_marked(self, tmp_path: Path) -> None:
        pdf = tmp_path / "wrong.pdf"
        doc = fitz.open()
        doc.new_page().insert_text((50, 50), "Another paper entirely")
        doc.save(str(pdf))
        doc.close()
        src = asyncio.run(resolve_source(_ref(pdf_path=pdf)))
        assert src.coverage == "abstract_only" and src.doc is not None
        assert src.doc.quality_reason == "reference_mismatch"
        assert "different paper" in src.detail

    @pytest.mark.parametrize("source", ["pdf", None])
    def test_abstract_not_from_an_api_record_is_not_trusted(self, source: str | None) -> None:
        ref = _ref(abstract_source=source)
        assert mismatch_abstract_document(ref) is None
        src = asyncio.run(resolve_source(ref))
        assert src.doc is None and src.cannot_verify_reason == "reference_mismatch"


class TestTooShortToJudge:
    """V5.6 E3: a stub abstract never stands in for a wrong/unusable PDF."""

    _ONE_LINER = "Registry heart transplant volumes rose in the most recent cohort."

    @pytest.mark.parametrize(("text", "ok"), [
        (_ABSTRACT, True),
        (_ONE_LINER, False),  # editor's one-line summary
        ("x" * 400, False),  # one "sentence", however long
        (_ABSTRACT[:290], False),  # under 300 characters
        ("Registry 2017 Annual Data Report. " + "Heart. " * 10, False),  # the title + stub
        ("", False),
    ])
    def test_judgeable(self, text: str, ok: bool) -> None:
        assert judgeable_abstract(text, "Registry 2017 Annual Data Report") is ok

    _FIRST = ("Islet grafts in a porous gel were placed under the kidney capsule of diabetic "
              "rats and followed for ninety days to assess graft function and inflammation.")
    _SECOND = (" imaging showed lower uptake in treated grafts than in controls at every time "
               "point, and graft function was kept in most treated recipients to the end.")

    @pytest.mark.parametrize("start", ["18F-FDG", "mRNA profiling with", "p53 staining and",
                                       "iPSC-derived islet", "α-cells and"])
    def test_a_second_sentence_may_start_with_anything(self, start: str) -> None:
        assert judgeable_abstract(f"{self._FIRST} {start}{self._SECOND}")

    def test_a_long_single_sentence_is_judgeable_and_abbreviations_end_nothing(self) -> None:
        one = self._FIRST[:-1] + "," + self._SECOND.replace(".", ",") + " with " \
            + "pancreas and liver tissue samples studied by two observers " * 2 + "too."
        assert len(one.split()) >= 50 and judgeable_abstract(one)
        stub = ("Immunoisolating microencapsulated pancreatic islet allografts, e.g. "
                "alginate microcapsules characterized by Smith et al. investigators, showed "
                "prolonged normoglycaemia, diminished pericapsular fibrotic overgrowth, "
                "attenuated proinflammatory cytokine production and preserved glucose-"
                "stimulated insulin secretion within transplanted recipients' peritoneum")
        assert len(stub) >= 300 and len(stub.split()) < 50 and not judgeable_abstract(stub)

    def test_mismatch_with_a_one_liner_is_reference_mismatch(self) -> None:
        src = asyncio.run(resolve_source(_ref(abstract_text=self._ONE_LINER,
                                              abstract_source="crossref")))
        assert src.doc is None and src.cannot_verify_reason == "reference_mismatch"
        assert "different paper" in src.detail and "too short" in src.detail

    @pytest.mark.parametrize(("quality", "reason"), [
        ("pdf_scanned", "pdf_scanned"), ("likely_supplement", "pdf_supplement")])
    def test_scan_or_supplement_with_a_one_liner(self, quality: QualityReason, reason: str,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
        async def load(ref: Reference) -> object:
            return build_abstract_document(ref.id, self._ONE_LINER, quality)

        monkeypatch.setattr(source_resolve, "load_source_document_async", load)
        src = asyncio.run(resolve_source(_ref(identity_status="verified")))
        assert src.doc is None and src.cannot_verify_reason == reason
        assert "too short" in src.detail

    def test_long_enough_fallback_still_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def load(ref: Reference) -> object:
            return build_abstract_document(ref.id, _ABSTRACT, "pdf_scanned")

        monkeypatch.setattr(source_resolve, "load_source_document_async", load)
        src = asyncio.run(resolve_source(_ref(identity_status="verified")))
        assert src.doc is not None and src.coverage == "abstract_only"


class TestFallbackReason:
    @pytest.mark.parametrize(("quality", "expected"), [
        ("reference_mismatch", "reference_mismatch"),
        ("pdf_scanned", "pdf_scanned"),
        ("pdf_unreadable", "pdf_scanned"),
        ("likely_supplement", "pdf_supplement"),
        ("metadata_only", "pdf_metadata_only"),
        ("abstract_only", None),  # no PDF at all: plain abstract verification
    ])
    def test_mapping(self, quality: QualityReason, expected: str | None) -> None:
        assert fallback_reason(build_abstract_document(22, _ABSTRACT, quality)) == expected

    def test_full_text_document_has_no_fallback(self) -> None:
        assert fallback_reason(build_source_document(22, "Results\n" + _ABSTRACT * 5)) is None

    def test_classify_quality_reason_knows_new_reasons(self) -> None:
        assert classify_quality_reason("pdf_scanned", 0.0) == CannotVerifyReason.PDF_SCANNED
        assert classify_quality_reason("reference_mismatch", 0.5) \
            == CannotVerifyReason.REFERENCE_MISMATCH


class TestAnnotate:
    def test_not_supported_on_wrong_paper_becomes_reference_mismatch(self) -> None:
        # case 3: verdict on the wrong edition must not be "not_supported"
        out = annotate_source_fallback(_result("not_supported"),
                                       build_abstract_document(22, _ABSTRACT,
                                                               "reference_mismatch"))
        assert out.verdict == "cannot_verify" and out.confidence == 0.0
        assert out.cannot_verify_reason == "reference_mismatch" and out.needs_user_review
        assert out.reasoning.startswith("The attached PDF is a different paper")

    @pytest.mark.parametrize(("quality", "expected"), [
        ("pdf_scanned", "pdf_scanned"), ("likely_supplement", "pdf_supplement")])
    def test_abstract_insufficient_replaced_by_pdf_problem(
        self, quality: QualityReason, expected: str,
    ) -> None:
        out = annotate_source_fallback(_result("cannot_verify", "abstract_insufficient"),
                                       build_abstract_document(22, _ABSTRACT, quality))
        assert out.cannot_verify_reason == expected

    def test_not_relevant_also_converted(self) -> None:
        typed = _result("not_relevant").model_copy(update={
            "partial_type": "tangential_source", "partial_severity": "major",
            "author_action": "Replace or move this citation.",
            "unsupported_elements": ["the main point"], "guards_applied": ["cocited_share"]})
        out = annotate_source_fallback(typed,
                                       build_abstract_document(22, _ABSTRACT, "pdf_scanned"))
        assert out.verdict == "cannot_verify" and out.cannot_verify_reason == "pdf_scanned"
        # The dropped verdict's sub-type fields go with it.
        assert (out.partial_type, out.partial_severity, out.author_action) == (None, None, "")
        assert out.unsupported_elements == [] and out.guards_applied == []

    def test_llm_error_kept(self) -> None:
        out = annotate_source_fallback(_result("cannot_verify", "llm_error"),
                                       build_abstract_document(22, _ABSTRACT, "pdf_scanned"))
        assert out.cannot_verify_reason == "llm_error"

    def test_positive_verdict_kept_but_flagged(self) -> None:
        out = annotate_source_fallback(_result("supported"),
                                       build_abstract_document(22, _ABSTRACT,
                                                               "likely_supplement"))
        assert out.verdict == "supported" and out.needs_user_review
        assert "supplementary material" in out.reasoning

    def test_plain_abstract_and_full_text_untouched(self) -> None:
        result = _result("not_supported")
        assert annotate_source_fallback(result, build_abstract_document(22, _ABSTRACT)) is result
        full = build_source_document(22, "Results\n" + _ABSTRACT * 5)
        assert annotate_source_fallback(result, full) is result
