"""Bibliography and source problems, per reference, for the report and the UI.

The pipeline detects them in different stages (duplicates and year letters in
parsing, ambiguous mappings in citation detection, wrong-paper PDFs and
repaired titles in gap resolution, scans and supplements in verification),
but nothing collected them, so a wrong PDF or a duplicate entry only showed
up as odd verdicts. Everything here is rebuilt from persisted fields
(``duplicate_of``, not the unpersisted parse warnings) so a regenerated
report shows the same issues.
"""

from typing import Literal

from pydantic import BaseModel, Field

from refcheck.models.claim import Claim
from refcheck.models.reference import Reference
from refcheck.models.verification import VerificationResult
from refcheck.stages.generate_report.claim_signals import mapping_text
from refcheck.stages.generate_report.result_signals import SourceProblem, source_problem
from refcheck.utils.doi import dois_match

SourceIssueKind = Literal["retracted", "wrong_pdf", "scanned_pdf", "supplement_pdf",
                          "metadata_only_pdf", "replaced_pdf", "duplicate",
                          "ambiguous_citation", "title_fixed"]

ISSUE_LABELS: dict[SourceIssueKind, str] = {
    "retracted": "Retracted or corrected",
    "wrong_pdf": "Attached PDF is a different paper",
    "scanned_pdf": "Attached PDF is a scan without text",
    "supplement_pdf": "Attached PDF is the supplement only",
    "metadata_only_pdf": "Attached PDF holds only a metadata page",
    "replaced_pdf": "Uploaded PDF unusable; a library / open-access copy was used",
    "duplicate": "Duplicate reference",
    "ambiguous_citation": "In-text citation matches several references",
    "title_fixed": "Garbled title replaced from the DOI/PMID record",
}
_PDF_KIND: dict[SourceProblem, SourceIssueKind] = {
    "reference_mismatch": "wrong_pdf", "pdf_scanned": "scanned_pdf",
    "pdf_supplement": "supplement_pdf", "pdf_metadata_only": "metadata_only_pdf",
}
_PDF_ADVICE: dict[SourceIssueKind, str] = {
    "wrong_pdf": "the attached PDF is a different paper; attach the cited article",
    "scanned_pdf": "the attached PDF has no usable text layer (a scan, or only a "
                   "repository cover page); attach a text PDF",
    "supplement_pdf": "the attached PDF is the supplementary material; attach the "
                      "main article",
    "metadata_only_pdf": "the attached PDF holds only a metadata page; attach the "
                         "full article",
}


class SourceIssue(BaseModel):
    """One bibliography / source problem and the claims it affects."""

    kind: SourceIssueKind
    reference_ids: list[int]
    claim_ids: list[int] = Field(default_factory=list)
    message: str


def _label(ref: Reference | None, ref_id: int) -> str:
    title = (ref.title or "").strip() if ref else ""
    return f"[{ref_id}] {title[:90]}".rstrip()


def _retracted(refs: list[Reference]) -> list[SourceIssue]:
    return [SourceIssue(kind="retracted", reference_ids=[r.id], message=(
        f"{_label(r, r.id)}: {r.retraction_status.replace('_', ' ')}"
        + (f" — {r.retraction_detail}" if r.retraction_detail else "")))
        for r in refs if r.retraction_status not in ("ok", "unknown")]


def _pdf_problems(refs: list[Reference],
                  verifications: list[VerificationResult]) -> list[SourceIssue]:
    by_id = {r.id: r for r in refs}
    found: dict[tuple[int, SourceIssueKind], list[int]] = {
        (r.id, "wrong_pdf"): [] for r in refs if r.identity_status == "mismatch"}
    for v in verifications:
        problem = source_problem(v)
        if problem is not None:
            claims = found.setdefault((v.reference_id, _PDF_KIND[problem]), [])
            if v.claim_id not in claims:
                claims.append(v.claim_id)
    return [SourceIssue(kind=kind, reference_ids=[ref_id], claim_ids=sorted(claims),
                        message=f"{_label(by_id.get(ref_id), ref_id)}: {_PDF_ADVICE[kind]}.")
            for (ref_id, kind), claims in sorted(found.items())]


_UPLOAD_PROBLEM = {"identity_mismatch": "a different paper", "supplement": "the supplement only",
                   "scanned": "a scan without text", "no_text": "no readable text"}
_COPY_FROM = {"library": "your PDF library", "open_access": "an open-access copy"}


def _replaced(refs: list[Reference]) -> list[SourceIssue]:
    """V5.8 G3: an unusable upload replaced by a library / open-access copy (the
    replacement is checked, but the user's own file is still wrong)."""
    return [SourceIssue(kind="replaced_pdf", reference_ids=[r.id], message=(
        f"{_label(r, r.id)}: the uploaded PDF is "
        f"{_UPLOAD_PROBLEM.get(r.replaced_upload_reason, 'unusable')}; the PDF from "
        f"{_COPY_FROM.get(r.pdf_source or '', 'another source')} was used instead - replace "
        "the attached file with the cited article."))
        for r in refs if r.replaced_upload_reason]


def _duplicates(refs: list[Reference]) -> list[SourceIssue]:
    by_id = {r.id: r for r in refs}
    issues: list[SourceIssue] = []
    for ref in refs:
        if ref.duplicate_of is None:
            continue
        first = by_id.get(ref.duplicate_of)
        why = (f"same DOI {ref.doi}" if first is not None and dois_match(ref.doi, first.doi)
               else "same title, first author and year")
        issues.append(SourceIssue(
            kind="duplicate", reference_ids=[ref.duplicate_of, ref.id],
            message=(f"[{ref.id}] repeats [{ref.duplicate_of}] ({why}); merge the two "
                     "entries and point their citations to one.")))
    return issues


def _ambiguous(claims: list[Claim]) -> list[SourceIssue]:
    grouped: dict[str, SourceIssue] = {}
    for claim in claims:
        text = mapping_text(claim)
        if not text:
            continue
        issue = grouped.setdefault(text, SourceIssue(
            kind="ambiguous_citation", message=text,
            reference_ids=sorted(set(claim.candidate_reference_ids or claim.reference_ids))))
        issue.claim_ids.append(claim.id)
    return list(grouped.values())


def _titles_fixed(refs: list[Reference]) -> list[SourceIssue]:
    return [SourceIssue(kind="title_fixed", reference_ids=[r.id], message=(
        f"[{r.id}] the title in the reference list looked garbled (journal/pages or DOI "
        f"captured instead); the record's title was used: “{r.title}”. Check the entry."))
        for r in refs if r.repair_applied == "title_from_api"]


def collect_source_issues(
    refs: list[Reference], claims: list[Claim], verifications: list[VerificationResult],
) -> list[SourceIssue]:
    """All bibliography / source issues, most serious kinds first."""
    return [*_retracted(refs), *_pdf_problems(refs, verifications), *_replaced(refs),
            *_duplicates(refs), *_ambiguous(claims), *_titles_fixed(refs)]
