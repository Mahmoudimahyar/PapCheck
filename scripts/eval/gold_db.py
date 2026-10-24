"""Read-only access to one RefCheck session in ~/.refcheck/refcheck.db.

The database is opened with a `mode=ro` URI: the eval never writes app state.
Claims are per (sentence, reference) pair; verifications are keyed by the
session's claim number and reference number.
"""

import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

from gold_models import COCITED_ABSTRACT_CHARS, CoCitedRef, normalize_sentence
from pydantic import BaseModel, Field

DEFAULT_DB = Path.home() / ".refcheck" / "refcheck.db"
PairKey = tuple[str, int]  # (normalised sentence, reference number)


class DbClaim(BaseModel):
    number: int
    sentence: str
    claim: str
    refs: list[int]
    paragraph: str = ""
    section: str = ""
    claim_type: str = "factual"
    claim_quality: str = "ok"
    co_cited_count: int = 1
    cited_for: str = ""


class DbReference(BaseModel):
    number: int
    title: str = ""
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    doi: str | None = None
    pdf_path: str | None = None
    abstract: str | None = None
    abstract_source: str | None = None
    identity_status: str = "unverified"
    duplicate_of: int | None = None


class DbVerification(BaseModel):
    claim_number: int
    ref: int
    verdict: str
    confidence: float = 0.0
    reasoning: str = ""
    coverage: str = ""
    needs_review: bool = False
    cannot_verify_reason: str | None = None
    decided_by: str = "none"
    consensus_type: str = ""
    layer_path: list[str] = Field(default_factory=list)
    model_reasoning: str = "[]"  # raw JSON list of ModelReasoning entries
    screen_p_support: float | None = None
    cost_usd: float = 0.0
    latency_ms: int = 0
    partial_type: str = ""  # V5.4 columns; "" on runs stored before them
    guards_applied: list[str] = Field(default_factory=list)


class SessionData(BaseModel):
    session_id: str
    claims: list[DbClaim]
    references: dict[int, DbReference]
    verifications: dict[tuple[int, int], DbVerification] = Field(default_factory=dict)

    def pair_index(self) -> dict[PairKey, list[int]]:
        """(normalised sentence, ref) -> claim numbers (a sentence can repeat)."""
        index: dict[PairKey, list[int]] = defaultdict(list)
        for claim in self.claims:
            for ref in claim.refs:
                index[(normalize_sentence(claim.sentence), ref)].append(claim.number)
        return dict(index)

    def co_cited(self, sentence: str, ref: int) -> list[CoCitedRef]:
        """The other references cited by claims with the same sentence (title + abstract)."""
        key = normalize_sentence(sentence)
        numbers = sorted({r for c in self.claims if normalize_sentence(c.sentence) == key
                          for r in c.refs if r != ref})
        out: list[CoCitedRef] = []
        for number in numbers:
            other = self.references.get(number)
            out.append(CoCitedRef(ref=number, title=other.title if other else "",
                                  abstract=clip_abstract(other.abstract if other else None)))
        return out


def clip_abstract(text: str | None, limit: int = COCITED_ABSTRACT_CHARS) -> str | None:
    """Whitespace-normalised abstract cut at a word boundary to <= limit chars (None if empty)."""
    clean = " ".join((text or "").split())
    if len(clean) <= limit:
        return clean or None
    head = clean[:limit + 1]
    return (head.rsplit(" ", 1)[0] if " " in head else clean[:limit]).rstrip()


def connect_ro(db_path: Path) -> sqlite3.Connection:
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def _claims(con: sqlite3.Connection, session: str) -> list[DbClaim]:
    rows = con.execute("SELECT * FROM claims WHERE session_id = ? ORDER BY claim_number",
                       (session,)).fetchall()
    return [DbClaim(
        number=r["claim_number"], sentence=r["manuscript_text"], claim=r["extracted_claim"],
        refs=json.loads(r["reference_ids_json"] or "[]"), paragraph=r["paragraph_text"] or "",
        section=r["section_heading"] or "", claim_type=r["claim_type"] or "factual",
        claim_quality=r["claim_quality"] or "ok", co_cited_count=r["co_cited_count"] or 1,
        cited_for=r["cited_for"] or "") for r in rows]


def _references(con: sqlite3.Connection, session: str) -> dict[int, DbReference]:
    rows = con.execute('SELECT * FROM "references" WHERE session_id = ?', (session,)).fetchall()
    return {r["ref_number"]: DbReference(
        number=r["ref_number"], title=r["title"] or "", authors=json.loads(r["authors_json"]
                                                                          or "[]"),
        year=r["year"], doi=r["doi"], pdf_path=r["pdf_path"], abstract=r["abstract_text"],
        abstract_source=r["abstract_source"], identity_status=r["identity_status"]
        or "unverified", duplicate_of=r["duplicate_of"]) for r in rows}


def _verifications(con: sqlite3.Connection, session: str,
                   ) -> dict[tuple[int, int], DbVerification]:
    rows = con.execute("SELECT * FROM verifications WHERE session_id = ?", (session,)).fetchall()
    return {(r["claim_id"], r["reference_id"]): DbVerification(
        claim_number=r["claim_id"], ref=r["reference_id"], verdict=r["verdict"],
        confidence=r["confidence"] or 0.0, reasoning=r["reasoning"] or "",
        coverage=r["source_coverage"] or "", needs_review=bool(r["needs_user_review"]),
        cannot_verify_reason=r["cannot_verify_reason"], decided_by=r["decided_by"] or "none",
        consensus_type=r["consensus_type"] or "",
        layer_path=json.loads(r["layer_path_json"] or "[]"),
        model_reasoning=r["model_reasoning_json"] or "[]",
        screen_p_support=r["screen_p_support"], cost_usd=r["cost_usd"] or 0.0,
        latency_ms=r["latency_ms"] or 0, **_v54_fields(r)) for r in rows}


def _v54_fields(row: sqlite3.Row) -> dict[str, Any]:
    """partial_type / guards_applied when the DB has the V5.4 columns."""
    keys = row.keys()
    return {
        "partial_type": (row["partial_type"] or "") if "partial_type" in keys else "",
        "guards_applied": json.loads(row["guards_applied_json"] or "[]")
        if "guards_applied_json" in keys else [],
    }


def load_session(session: str, db_path: Path = DEFAULT_DB,
                 with_verifications: bool = True) -> SessionData:
    """Claims, references (and verifications) of one session, read-only."""
    con = connect_ro(db_path)
    try:
        claims = _claims(con, session)
        if not claims:
            raise ValueError(f"Session {session} has no claims in {db_path}")
        return SessionData(session_id=session, claims=claims,
                           references=_references(con, session),
                           verifications=_verifications(con, session)
                           if with_verifications else {})
    finally:
        con.close()


def production_pdf(refs: dict[int, DbReference], ref: DbReference) -> DbReference:
    """The reference as verification sees it: a duplicate entry without a PDF/abstract
    inherits its original's (same rule as duplicate_sources.inherit_duplicate_sources)."""
    original = refs.get(ref.duplicate_of) if ref.duplicate_of is not None else None
    if original is None or original.number == ref.number:
        return ref
    update: dict[str, object] = {}
    if ref.pdf_path is None and original.pdf_path is not None:
        update.update(pdf_path=original.pdf_path, identity_status=original.identity_status)
    if not ref.abstract and original.abstract:
        update.update(abstract=original.abstract, abstract_source=original.abstract_source)
    return ref.model_copy(update=update) if update else ref
