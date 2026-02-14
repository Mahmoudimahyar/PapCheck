"""V1 report sections: executive summary, findings, methodology."""

import logging
from typing import TYPE_CHECKING

from docx.shared import Pt, RGBColor

from refcheck.models.claim import Claim
from refcheck.models.reference import Reference
from refcheck.models.verification import VerificationResult

if TYPE_CHECKING:
    from docx.document import Document as DocxDocument

logger = logging.getLogger(__name__)

_GREEN = RGBColor(0x16, 0xA3, 0x4A)
_RED = RGBColor(0xDC, 0x26, 0x26)
_AMBER = RGBColor(0xD9, 0x77, 0x06)
_GRAY = RGBColor(0x9C, 0xA3, 0xAF)

_VERDICT_COLORS: dict[str, RGBColor] = {
    "supported": _GREEN,
    "partially_supported": _AMBER,
    "not_supported": _RED,
    "contradicted": _RED,
    "cannot_verify": _GRAY,
}


def add_executive_summary(
    doc: "DocxDocument",
    verifications: list[VerificationResult],
) -> None:
    """Add executive summary with color-coded verdict counts."""
    doc.add_heading("Executive Summary", level=2)

    counts = _count_verdicts(verifications)
    total = len(verifications)

    doc.add_paragraph(f"Total claim-reference pairs verified: {total}")
    _add_colored_line(doc, f"Supported: {counts['supported']}", _GREEN)
    _add_colored_line(doc, f"Partially supported: {counts['partially_supported']}", _AMBER)
    _add_colored_line(doc, f"Not supported: {counts['not_supported']}", _RED)
    _add_colored_line(doc, f"Contradicted: {counts['contradicted']}", _RED)
    _add_colored_line(doc, f"Cannot verify: {counts['cannot_verify']}", _GRAY)


def add_critical_findings(
    doc: "DocxDocument",
    verifications: list[VerificationResult],
    claims_by_id: dict[int, Claim],
) -> None:
    """Add critical findings (contradicted / not supported verdicts)."""
    critical = [
        v for v in verifications
        if v.verdict in ("not_supported", "contradicted")
    ]
    if not critical:
        return

    doc.add_heading("Critical Findings", level=2)
    doc.add_paragraph(
        f"{len(critical)} claim(s) flagged as problematic:"
    )

    for v in critical:
        _add_finding_detail(doc, v, claims_by_id)


def add_minor_issues(
    doc: "DocxDocument",
    verifications: list[VerificationResult],
    claims_by_id: dict[int, Claim],
) -> None:
    """Add minor issues (partially supported verdicts)."""
    partial = [v for v in verifications if v.verdict == "partially_supported"]
    if not partial:
        return

    doc.add_heading("Minor Issues", level=2)
    for v in partial:
        _add_finding_detail(doc, v, claims_by_id)


def add_verified_section(
    doc: "DocxDocument",
    verifications: list[VerificationResult],
) -> None:
    """Add brief section for all supported verdicts."""
    supported = [v for v in verifications if v.verdict == "supported"]
    if not supported:
        return

    doc.add_heading("Verified References", level=2)
    doc.add_paragraph(
        f"{len(supported)} claims verified as supported by their cited sources."
    )


def add_methodology_note(doc: "DocxDocument", total: int) -> None:
    """Add methodology note about LLM and verification approach."""
    doc.add_heading("Methodology Note", level=2)
    doc.add_paragraph(
        "This report was generated using RefCheck AI's automated "
        "verification system."
    )
    doc.add_paragraph(
        "Model: Claude Sonnet 4.5 (claude-sonnet-4-5-20250514) via litellm"
    )
    doc.add_paragraph("Verification tier: Tier 1 (single-model forced grounding)")
    doc.add_paragraph(f"Total claim-reference pairs analyzed: {total}")
    doc.add_paragraph(
        "Confidence scores reflect textual evidence strength. "
        "Scores below 0.5 indicate insufficient evidence."
    )


def _count_verdicts(verifications: list[VerificationResult]) -> dict[str, int]:
    """Count verdicts by type."""
    counts = {
        "supported": 0, "partially_supported": 0,
        "not_supported": 0, "contradicted": 0, "cannot_verify": 0,
    }
    for v in verifications:
        if v.verdict in counts:
            counts[v.verdict] += 1
    return counts


def _add_colored_line(
    doc: "DocxDocument", text: str, color: RGBColor,
) -> None:
    """Add a paragraph with colored text."""
    para = doc.add_paragraph()
    run = para.add_run(text)
    run.font.color.rgb = color
    run.font.size = Pt(11)


def _add_finding_detail(
    doc: "DocxDocument",
    result: VerificationResult,
    claims_by_id: dict[int, Claim],
) -> None:
    """Add detail for a single finding."""
    claim = claims_by_id.get(result.claim_id)
    verdict_text = result.verdict.upper().replace("_", " ")
    color = _VERDICT_COLORS.get(result.verdict, _GRAY)

    doc.add_paragraph(f"Claim {result.claim_id} / Reference {result.reference_id}")

    if claim:
        doc.add_paragraph(f"Manuscript: \"{claim.manuscript_text}\"")
        doc.add_paragraph(f"Claim: {claim.extracted_claim}")

    para = doc.add_paragraph("Verdict: ")
    run = para.add_run(verdict_text)
    run.bold = True
    run.font.color.rgb = color

    if result.evidence_quotes:
        doc.add_paragraph("Evidence from source:")
        for quote in result.evidence_quotes:
            doc.add_paragraph(f'  "{quote}"', style="List Bullet")

    if result.reasoning:
        doc.add_paragraph(f"Reasoning: {result.reasoning}")

    doc.add_paragraph(
        f"Confidence: {result.confidence:.0%} | "
        f"Tier: {result.tier} | "
        f"Coverage: {result.source_coverage}"
    )
    doc.add_paragraph("")  # Spacer


def add_retraction_section(
    doc: "DocxDocument",
    references: list[Reference],
) -> None:
    """Add retraction warning section if any references are retracted/corrected."""
    flagged = [
        r for r in references
        if r.retraction_status not in ("ok", "unknown")
    ]
    if not flagged:
        return
    doc.add_heading("RETRACTED OR CORRECTED REFERENCES", level=2)
    para = doc.add_paragraph()
    run = para.add_run(f"WARNING: {len(flagged)} reference(s) have been flagged:")
    run.bold = True
    run.font.color.rgb = _RED
    for ref in flagged:
        status = ref.retraction_status.upper().replace("_", " ")
        doc.add_paragraph(
            f"[{ref.id}] {ref.title}: {status} — {ref.retraction_detail}",
            style="List Bullet",
        )
