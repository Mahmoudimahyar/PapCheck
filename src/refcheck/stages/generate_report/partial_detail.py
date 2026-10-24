"""V5.4 partial sub-type lines of one finding and the "How to read partial verdicts" legend.

A finding shows its type (label + minor/major), the elements the source does
not state, and one sentence telling the author what to do; a result whose
concern a benign guard cleared shows "Cleared: <guard>" with the reason (only a
supported result: on any other verdict the concern was not cleared). Fields a
reviewer override made stale are hidden by the ``partial_findings`` accessors.
Wording comes from ``models/partial_types.py``.
"""

from typing import TYPE_CHECKING

from refcheck.models.partial_types import GUARD_LABELS
from refcheck.models.verification import VerificationResult
from refcheck.stages.generate_report.partial_findings import (
    action_of,
    elements_of,
    guards_of,
    partial_type_of,
    severity_of,
    type_label,
)
from refcheck.stages.generate_report.report_style import AMBER, RED, add_colored_line, add_labeled

if TYPE_CHECKING:
    from docx.document import Document as DocxDocument

LEGEND_TITLE = "How to read partial verdicts"
LEGEND_LINES: tuple[tuple[str, str], ...] = (
    ("Partially supported",
     "the cited source backs part of the sentence, but not all of it. Each finding is filed "
     "under one type: the most serious problem found, in the order of the sub-sections below."),
    ("Major", "the sentence states something the source does not (a different specific, a "
              "conclusion or scope the source does not reach). Fix these first."),
    ("Minor", "the core point is supported; a side element is missing or the wording is more "
              "certain than the source."),
    ("What to do", "a suggested fix for the author; 'not stated in the source' lists the parts "
                   "the checker could not find."),
    ("Could not verify (coverage)", "not a negative finding: only the abstract or part of the "
                                    "paper was available."),
    ("Supported with a note", "a concern was checked and cleared (co-cited reference, wording "
                              "only, author framing or an evidence re-check); see that section."),
)


def severity_text(severity: str | None) -> str:
    """" (major)" / " (minor)" / ""."""
    return f" ({severity})" if severity else ""


def add_partial_lines(doc: "DocxDocument", result: VerificationResult) -> None:
    """Type, missing elements and author action of a non-supported finding; guard notes
    of a supported one."""
    if result.verdict == "supported":
        _add_guard_lines(doc, result)
        return
    label = type_label(partial_type_of(result))
    if label:
        severity = severity_of(result)
        color = RED if severity == "major" else AMBER
        add_colored_line(doc, f"Issue type: {label}{severity_text(severity)}", color, bold=True)
        elements = elements_of(result)
        if elements:
            add_labeled(doc, "Not stated in the source", "; ".join(elements))
        action = action_of(result)
        if action:
            add_labeled(doc, "What to do", action)


def _add_guard_lines(doc: "DocxDocument", result: VerificationResult) -> None:
    """"Cleared: <guard> - why" for each benign guard that cleared a concern."""
    for guard in guards_of(result):
        name, why = GUARD_LABELS[guard]
        add_labeled(doc, "Cleared", f"{name} — {why}")


def add_partial_legend(doc: "DocxDocument") -> None:
    """A short key to the partial types and severities."""
    doc.add_heading(LEGEND_TITLE, level=3)
    for label, text in LEGEND_LINES:
        add_labeled(doc, label, text, style="List Bullet")
