"""Case records of the tool-"supported" review sample (review_supported/cases.json).

Each case carries what a reviewer needs to judge one (sentence, reference) pair
against the cited paper: the manuscript context, the co-cited references, the
reference metadata/abstract, the tool's verdict with its explanation and quotes,
and where the paper's extracted text is. The DB is read with a `mode=ro` URI.
"""

import json
from pathlib import Path

from gold_db import SessionData, connect_ro, production_pdf
from gold_models import CoCitedRef
from pydantic import BaseModel, Field
from sample_supported_draw import Candidate
from sample_supported_text import PaperText

QuoteMap = dict[tuple[int, int], list[str]]  # (claim number, ref) -> tool evidence quotes


class SupportedCase(BaseModel):
    """One pair to review."""

    case: int
    pair_id: str
    claim_number: int
    sentence: str
    claim: str
    cited_for: str = ""
    paragraph: str = ""
    section: str = ""
    stratum: str  # "multi" | "single" (+ ", abstract_only" when forced in)
    co_cited_count: int = 1
    co_cited_refs: list[CoCitedRef] = Field(default_factory=list)
    ref: int
    title: str = ""
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    doi: str | None = None
    identity_status: str = ""
    abstract: str = ""
    coverage: str = ""
    tool_verdict: str
    tool_confidence: float = 0.0
    tool_consensus: str = ""
    tool_explanation: str = ""
    tool_quotes: list[str] = Field(default_factory=list)
    layer_path: list[str] = Field(default_factory=list)
    pdf_path: str | None = None
    text_file: str = ""
    text_chars: int = 0
    text_notes: list[str] = Field(default_factory=list)


def load_quotes(db: Path, session: str) -> QuoteMap:
    """The tool's evidence quotes per verification (not part of gold_db's loader)."""
    con = connect_ro(db)
    try:
        rows = con.execute("SELECT claim_id, reference_id, evidence_quotes_json FROM "
                           "verifications WHERE session_id = ?", (session,)).fetchall()
    finally:
        con.close()
    return {(r["claim_id"], r["reference_id"]): json.loads(r["evidence_quotes_json"] or "[]")
            for r in rows}


def build_case(num: int, cand: Candidate, session: SessionData, quotes: QuoteMap,
               text: PaperText, para_chars: int, forced: set[str]) -> SupportedCase:
    claim = next(c for c in session.claims if c.number == cand.claim_number)
    ref = production_pdf(session.references, session.references[cand.ref])
    ver = session.verifications[(cand.claim_number, cand.ref)]
    stratum = ("multi" if cand.multi else "single") + \
        (", abstract_only" if cand.pair_id in forced else "")
    return SupportedCase(
        case=num, pair_id=cand.pair_id, claim_number=claim.number, sentence=claim.sentence,
        claim=claim.claim, cited_for=claim.cited_for, paragraph=claim.paragraph[:para_chars],
        section=claim.section, stratum=stratum, co_cited_count=claim.co_cited_count,
        co_cited_refs=session.co_cited(claim.sentence, cand.ref), ref=cand.ref,
        title=ref.title, authors=ref.authors, year=ref.year, doi=ref.doi,
        identity_status=ref.identity_status, abstract=ref.abstract or "",
        coverage=ver.coverage, tool_verdict=ver.verdict, tool_confidence=ver.confidence,
        tool_consensus=ver.consensus_type, tool_explanation=ver.reasoning,
        tool_quotes=quotes.get((cand.claim_number, cand.ref), []), layer_path=ver.layer_path,
        pdf_path=ref.pdf_path, text_file=text.text_file, text_chars=text.chars,
        text_notes=text.notes)
