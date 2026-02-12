"""Generate existence report as DOCX using python-docx."""

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import docx
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.shared import Inches, Pt, RGBColor

from refcheck.models.pipeline import PipelineState
from refcheck.models.reference import Reference

if TYPE_CHECKING:
    from docx.document import Document as DocxDocument
    from docx.table import _Cell

logger = logging.getLogger(__name__)

_GREEN = RGBColor(0x16, 0xA3, 0x4A)
_RED = RGBColor(0xDC, 0x26, 0x26)
_AMBER = RGBColor(0xD9, 0x77, 0x06)
_GRAY = RGBColor(0x9C, 0xA3, 0xAF)


def generate_report(state: PipelineState, output_path: Path) -> Path:
    """Generate an MVP existence report DOCX from pipeline state."""
    doc = docx.Document()
    _add_title(doc, state)
    _add_summary(doc, state)
    _add_reference_table(doc, state.references)
    _add_not_found_section(doc, state.references)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    logger.info("Report saved to %s", output_path)
    return output_path


def _add_title(doc: "DocxDocument", state: PipelineState) -> None:
    """Add report title and metadata."""
    doc.add_heading("RefCheck AI — Reference Existence Report", level=1)
    filename = state.manuscript.filename if state.manuscript else "Unknown"
    doc.add_paragraph(f"Manuscript: {filename}")
    doc.add_paragraph(f"Session: {state.session_id}")


def _add_summary(doc: "DocxDocument", state: PipelineState) -> None:
    """Add summary statistics section."""
    doc.add_heading("Summary", level=2)
    refs = state.references
    total = len(refs)
    found = sum(1 for r in refs if r.source_status == "found")
    not_found = sum(1 for r in refs if r.source_status == "not_found")
    api_error = sum(1 for r in refs if r.source_status == "api_error")
    with_pdf = sum(1 for r in refs if r.pdf_path is not None)

    doc.add_paragraph(f"Total references: {total}")
    doc.add_paragraph(f"Found in databases: {found}")
    doc.add_paragraph(f"Not found: {not_found}")
    doc.add_paragraph(f"API errors: {api_error}")
    doc.add_paragraph(f"PDFs available: {with_pdf}")


def _add_reference_table(
    doc: "DocxDocument",
    references: list[Reference],
) -> None:
    """Add reference status table."""
    doc.add_heading("Reference Status", level=2)
    if not references:
        doc.add_paragraph("No references to display.")
        return

    table = doc.add_table(rows=1, cols=5)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Table Grid"

    headers = ["#", "Title", "Authors", "Status", "PDF"]
    for idx, header in enumerate(headers):
        cell = table.rows[0].cells[idx]
        cell.text = header
        for paragraph in cell.paragraphs:
            for run in paragraph.runs:
                run.bold = True
                run.font.size = Pt(9)

    for ref in references:
        row = table.add_row()
        row.cells[0].text = str(ref.id)
        row.cells[1].text = ref.title[:60] + ("..." if len(ref.title) > 60 else "")
        row.cells[2].text = ", ".join(ref.authors[:2])
        row.cells[3].text = ref.source_status
        row.cells[4].text = _pdf_status_text(ref)
        _color_status_cell(row.cells[3], ref.source_status)

    for row_obj in table.rows:
        row_obj.cells[0].width = Inches(0.4)
        row_obj.cells[1].width = Inches(2.5)
        row_obj.cells[2].width = Inches(1.5)
        row_obj.cells[3].width = Inches(0.8)
        row_obj.cells[4].width = Inches(1.0)


def _pdf_status_text(ref: Reference) -> str:
    """Human-readable PDF status for a reference."""
    if ref.pdf_path:
        return ref.pdf_source or "available"
    if ref.journal_url:
        return "paywalled"
    return "missing"


def _color_status_cell(cell: "_Cell", status: str) -> None:
    """Apply color to a status cell based on reference status."""
    color_map = {
        "found": _GREEN,
        "not_found": _RED,
        "api_error": _AMBER,
        "pending": _GRAY,
    }
    color = color_map.get(status, _GRAY)
    for paragraph in cell.paragraphs:
        for run in paragraph.runs:
            run.font.color.rgb = color


def _add_not_found_section(
    doc: "DocxDocument",
    references: list[Reference],
) -> None:
    """Add section for not-found references with search details."""
    not_found = [r for r in references if r.source_status == "not_found"]
    if not not_found:
        return

    doc.add_heading("Not Found References", level=2)
    doc.add_paragraph(
        f"{len(not_found)} references could not be found in any database."
    )

    for ref in not_found:
        doc.add_paragraph(
            f"[{ref.id}] {ref.title or ref.raw_text[:80]}",
            style="List Bullet",
        )
        if ref.doi:
            doc.add_paragraph(f"  Searched DOI: {ref.doi}")
        if ref.pmid:
            doc.add_paragraph(f"  Searched PMID: {ref.pmid}")
