"""Identity status of a PDF file for one reference (gate for the match-stage re-match).

The match stage re-matches references to uploaded PDFs and must never link a
PDF the resolve stage would later flag as another paper. Stages do not import
each other, so the pipeline runner passes this function to the match stage.
"""

from pathlib import Path

from refcheck.models.reference import Reference
from refcheck.stages.resolve_gaps.identity_check import check_identity, read_first_pages_text


def pdf_identity_status(ref: Reference, pdf_path: Path) -> str:
    """Identity status of `pdf_path` for `ref`: verified, unverified or mismatch."""
    return check_identity(ref, read_first_pages_text(pdf_path)).status
