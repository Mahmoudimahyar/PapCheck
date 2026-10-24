"""DOCX report: V5 cascade statistics section."""

import docx

from refcheck.models.verification import VerificationResult
from refcheck.stages.generate_report.cost_section import add_cost_section


def _texts(results: list[VerificationResult]) -> list[str]:
    doc = docx.Document()
    add_cost_section(doc, results)
    return [p.text for p in doc.paragraphs]


def test_reports_decided_by_layers_cost_and_review() -> None:
    texts = _texts([
        VerificationResult(claim_id=1, reference_id=1, verdict="supported", decided_by="verifier",
                           layer_path=["screen", "verifier"], cost_usd=0.001),
        VerificationResult(claim_id=2, reference_id=1, verdict="contradicted", decided_by="judge",
                           layer_path=["screen", "verifier", "judge", "confirm"], cost_usd=0.03,
                           needs_user_review=True),
        VerificationResult(claim_id=3, reference_id=2, cannot_verify_reason="llm_error",
                           source_coverage="full_text"),
    ])
    assert "LLM cost for these pairs: $0.03" in texts
    assert "Flagged for human review: 1 (33.3%)" in texts
    assert "Could not be checked because of LLM/API errors: 1 (33.3%)" in texts
    assert "Judge (opt-in escalation): 1 (33.3%)" in texts
    assert "Cross-check (blind, other model family): 1 (33.3%)" in texts
    assert not any("Tier" in t or "V4" in t for t in texts)


def test_the_co_cited_union_check_is_a_reached_layer() -> None:
    texts = _texts([VerificationResult(
        claim_id=1, reference_id=1, verdict="supported", decided_by="verifier",
        layer_path=["verifier", "adjudicate", "adjudicate_cocited"])])
    assert any(t.startswith("Element check, co-cited references") and t.endswith("1 (100.0%)")
               for t in texts)


def test_empty_results_add_nothing() -> None:
    assert _texts([]) == []
