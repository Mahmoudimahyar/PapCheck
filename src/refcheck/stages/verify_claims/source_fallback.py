"""Abstract fallback when the attached PDF cannot stand for the cited article.

The PDF can be another paper (identity mismatch), a scan without text, the
supplementary material, or a metadata page. Verification then falls back to
the abstract, and the result must say why: a cannot_verify carries the PDF
problem as its reason (reference_mismatch / pdf_scanned / pdf_supplement /
pdf_metadata_only) instead of a generic "abstract_insufficient", and an
abstract can never produce not_supported / not_relevant. An abstract too short
to judge on (``judgeable_abstract``: under 300 characters, a single sentence of
fewer than SINGLE_SENTENCE_WORDS words, or little more than the title) never stands
in for the PDF (V5.6, E3). A sentence may start with anything ("18F-FDG imaging ...",
"mRNA profiling ...", "p53 ..."); an abbreviation ("et al.", "e.g.") or an initial
never ends one.
"""

import re

from refcheck.models.cannot_verify import PDF_PROBLEM_REASONS
from refcheck.models.reference import Reference
from refcheck.models.verification import VerificationResult
from refcheck.stages.verify_claims.source_document import build_abstract_document
from refcheck.stages.verify_claims.source_models import SourceDocument

# Abstracts fetched from an API record of the reference's own DOI/PMID (enrichment;
# Europe PMC counts only when its hit has the DOI/PMID asked for, see europepmc_client).
API_ABSTRACT_SOURCES = frozenset({"pubmed", "semantic_scholar", "europepmc", "crossref"})
_ABSENCE_VERDICTS = frozenset({"not_supported", "not_relevant"})
MIN_FALLBACK_ABSTRACT_CHARS = 300
_TITLE_SLACK_CHARS = 100  # an "abstract" this close to the title adds nothing to judge
SINGLE_SENTENCE_WORDS = 50  # a single sentence this long is a real (structured) abstract
_SENTENCE_END_RE = re.compile(r"(?P<word>[\w.]*)[.!?](?=\s+\S)")
_ABBREVIATIONS = frozenset({"al", "e.g", "i.e", "eg", "ie", "vs", "fig", "figs", "ref", "refs",
                            "approx", "ca", "cf", "no", "nos", "et", "resp", "incl"})
_NOTES: dict[str, str] = {
    "reference_mismatch": "The attached PDF is a different paper than this reference",
    "pdf_scanned": "The attached PDF is a scan without a usable text layer",
    "pdf_unreadable": "The attached PDF has no readable text",
    "likely_supplement": "The attached PDF is the supplementary material, not the article",
    "metadata_only": "The attached PDF holds only a metadata page",
}


def mismatch_abstract_document(ref: Reference) -> SourceDocument | None:
    """Abstract-only document for a reference whose PDF is another paper.

    Only an abstract from an API record of the reference itself qualifies; any
    other abstract could have come from the wrong PDF.
    """
    if (ref.abstract_source or "") not in API_ABSTRACT_SOURCES:
        return None
    doc = build_abstract_document(ref.id, ref.abstract_text or "", "reference_mismatch")
    return doc if doc.chunks else None


def judgeable_abstract(text: str, title: str | None = None) -> bool:
    """Whether an abstract standing in for an unusable PDF can carry a verdict.

    A stub under 300 characters, one sentence (an editor's summary) or the title
    with little else would let a verdict rest on the paper's title.
    """
    clean = " ".join((text or "").split())
    if len(clean) < MIN_FALLBACK_ABSTRACT_CHARS:
        return False
    if len(clean.split()) < SINGLE_SENTENCE_WORDS and not _sentence_ends(clean):
        return False
    heading = " ".join((title or "").lower().split()).rstrip(".")
    return not heading or not (heading in clean.lower()
                               and len(clean) - len(heading) < _TITLE_SLACK_CHARS)


def _sentence_ends(text: str) -> bool:
    """A sentence end followed by more text (not after an abbreviation or an initial)."""
    for match in _SENTENCE_END_RE.finditer(text):
        word = match.group("word").lower().strip(".")
        if word not in _ABBREVIATIONS and not (len(word) == 1 and word.isalpha()):
            return True
    return False


def short_fallback_note(quality_reason: str) -> str:
    """Why a PDF problem left nothing to verify on (the abstract is too short)."""
    problem = _NOTES.get(quality_reason, "The attached PDF cannot be used")
    return f"{problem}, and the abstract on record is too short to check the claim."


def fallback_reason(doc: SourceDocument) -> str | None:
    """cannot_verify reason of the PDF problem behind an abstract-only document."""
    if doc.coverage != "abstract_only":
        return None
    reason = PDF_PROBLEM_REASONS.get(doc.quality_reason)
    return str(reason) if reason is not None else None


def fallback_note(doc: SourceDocument) -> str:
    """User-facing sentence explaining an abstract fallback ("" when there is none)."""
    if fallback_reason(doc) is None:
        return ""
    return f"{_NOTES[doc.quality_reason]}; only the abstract was checked."


def source_note(doc: SourceDocument) -> str:
    """What the reader should know about the source text ("" when nothing)."""
    note = fallback_note(doc)
    if not note and doc.ocr_pages:
        note = f"Text of {doc.ocr_pages} scanned page(s) was obtained by OCR."
    return note


def annotate_source_fallback(
    result: VerificationResult, doc: SourceDocument,
) -> VerificationResult:
    """Make a result on an abstract fallback say why the PDF was not used.

    cannot_verify -> the PDF problem becomes the reason (an llm_error stays);
    not_supported / not_relevant -> cannot_verify with that reason (absence of
    a finding in an abstract proves nothing); other verdicts keep their label
    and are flagged for review so the PDF gets fixed.
    """
    reason = fallback_reason(doc)
    if reason is None:
        return result
    reasoning = f"{fallback_note(doc)} {result.reasoning}".strip()
    if result.verdict == "cannot_verify":
        keep = result.cannot_verify_reason == "llm_error"
        return result.model_copy(update={
            "cannot_verify_reason": result.cannot_verify_reason if keep else reason,
            "reasoning": reasoning})
    if result.verdict in _ABSENCE_VERDICTS:
        # The sub-type fields explained the dropped verdict (cannot_verify has none).
        return result.model_copy(update={
            "verdict": "cannot_verify", "confidence": 0.0, "cannot_verify_reason": reason,
            "reasoning": reasoning, "needs_user_review": True, "partial_type": None,
            "partial_severity": None, "author_action": "", "unsupported_elements": [],
            "guards_applied": []})
    return result.model_copy(update={"reasoning": reasoning, "needs_user_review": True})
