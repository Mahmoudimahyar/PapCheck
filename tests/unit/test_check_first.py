"""Partial verdicts that may hide a real problem are listed before the other partials.

Regression (integration review of the V5.2 dispute rule): a verifier
"not_supported" that the cross-check disputed is now SHOWN as
partially_supported, so the report filed it under "Minor Issues" next to
ordinary partial support. On the V4.9 manuscript that is where the genuinely
unsupported "<50%" and "150 kPa" figures (cases 40, 17) and the reviewer's
other real "not supported" calls (13, 15) ended up.
"""

from pathlib import Path

import docx

from refcheck.api.routes.report_helpers import collect_critical, collect_minor
from refcheck.models.claim import Claim
from refcheck.models.pipeline import PipelineState
from refcheck.models.reference import ParsedManuscript, Reference
from refcheck.models.verification import VerificationResult
from refcheck.stages.generate_report import generate_report
from refcheck.stages.generate_report.partial_sections import PARTIAL_HEADING
from refcheck.stages.generate_report.result_signals import check_first
from tests.unit.test_result_signals import _disputed

_MISSING = "Numbers not found in the source: 150 kPa — please check where they come from."


def _partial(claim_id: int, reasoning: str = "Partly stated.") -> VerificationResult:
    return VerificationResult(claim_id=claim_id, reference_id=1, verdict="partially_supported",
                              confidence=0.7, reasoning=reasoning, consensus_type="confirmed")


async def test_disputed_negative_shown_as_partial_is_check_first() -> None:
    softened = await _disputed("not_supported", "partially_supported")
    assert softened.verdict == "partially_supported" and check_first(softened)


async def test_positive_verifier_dispute_and_plain_partial_are_not_check_first() -> None:
    assert not check_first(_partial(1))
    kept = await _disputed("not_supported", "not_supported")  # confirmed negative
    assert kept.verdict == "not_supported" and not check_first(kept)


def test_missing_numbers_make_a_partial_check_first() -> None:
    assert check_first(_partial(1, f"Partly stated. {_MISSING}"))
    assert not check_first(_partial(1, "Partly stated.").model_copy(
        update={"verdict": "supported"}))


async def test_report_lists_check_first_before_and_apart_from_minor(tmp_path: Path) -> None:
    softened = (await _disputed("not_supported", "partially_supported")).model_copy(
        update={"claim_id": 1})
    numbers = _partial(2, f"Partly stated. {_MISSING}")
    plain = _partial(3)
    claims = [Claim(id=i, extracted_claim=f"Claim number {i}", reference_ids=[1])
              for i in (1, 2, 3)]
    state = PipelineState(session_id="s", manuscript=ParsedManuscript(filename="m.docx"),
                          references=[Reference(id=1, title="Paper", source_status="found")],
                          claims=claims, verification_results=[plain, softened, numbers])
    out = generate_report(state, tmp_path / "r.docx")
    text = "\n".join(p.text for p in docx.Document(str(out)).paragraphs)
    first = text.index("Check First: Disputed or Unconfirmed Details")
    minor = text.index(PARTIAL_HEADING)  # V5.4: replaces "Minor Issues"
    assert first < minor
    section = text[first:minor]
    assert "Claim number 1" in section and "Claim number 2" in section
    assert "Claim number 3" not in section and "Claim number 3" in text[minor:]
    assert section.index("Claim number 2") < section.index("Claim number 1")  # numbers first


async def test_preview_marks_and_leads_with_check_first() -> None:
    softened = (await _disputed("not_supported", "partially_supported")).model_copy(
        update={"claim_id": 2})
    rows = collect_minor([_partial(1), softened], {})
    assert [r["claim_id"] for r in rows] == ["2", "1"]
    assert [r["check_first"] for r in rows] == ["yes", ""]
    assert collect_critical([softened], {}) == []
