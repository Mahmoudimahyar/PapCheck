"""Figure-credit panels for gold rows: the production rule (verify_claims/credit.py).

A gold row's claim is judged on the legend panel its credit line closes, exactly as
verifier.with_credit_panels prepares it. When the credit sentence repeats in the
legend ("(A) ... Adapted from X. ... (C) ... Adapted from X."), which panel the row
closes is decided from its session's claims (their offsets, read from
~/.refcheck/refcheck.db opened read-only) with the production rule
(credit_position.credit_occurrences). Without the DB/session, the panels of all
identical credits are used (credit.credit_panel, as for a claim without offsets).
"""

import logging
import sqlite3
from functools import lru_cache
from pathlib import Path

from gold_db import DEFAULT_DB, connect_ro
from gold_models import GoldRow
from pydantic import ValidationError

from refcheck.models.claim import Claim
from refcheck.models.evidence import ClaimLocation
from refcheck.stages.verify_claims.credit import panel_claim
from refcheck.stages.verify_claims.credit_legend import credit_positions, is_credit_line
from refcheck.stages.verify_claims.credit_position import (
    credit_needle,
    credit_occurrences,
    credit_text,
)

logger = logging.getLogger(__name__)
_SQL = ("SELECT claim_number, manuscript_text, extracted_claim, cited_for, paragraph_text, "
        "location_json FROM claims WHERE session_id = ?")


def gold_panel_claim(row: GoldRow, claim: Claim, db_path: Path | None = None) -> Claim:
    """``claim`` (built from ``row``) prepared like production: CITED FOR = its panel."""
    if not is_credit_line(credit_text(claim)):
        return claim
    occurrence: int | None = None
    if len(credit_positions(credit_needle(claim), claim.paragraph_text)) > 1:
        claims = session_claims(row.session_id, str(db_path or DEFAULT_DB))
        occurrence = credit_occurrences(claims).get(row.claim_number)
    return panel_claim(claim, occurrence)


@lru_cache(maxsize=16)
def session_claims(session: str, db_path: str) -> tuple[Claim, ...]:
    """The session's claims with their offsets (() when the DB or session is missing)."""
    if not session or not Path(db_path).is_file():
        return ()
    try:
        con = connect_ro(Path(db_path))
        try:
            rows = con.execute(_SQL, (session,)).fetchall()
        finally:
            con.close()
        return tuple(_claim(r) for r in rows)
    except (sqlite3.Error, ValidationError) as exc:
        logger.warning("credit panels: session %s unreadable (%s)", session, exc)
        return ()


def _claim(row: sqlite3.Row) -> Claim:
    location = row["location_json"]
    return Claim(
        id=row["claim_number"], manuscript_text=row["manuscript_text"] or "",
        extracted_claim=row["extracted_claim"] or "", cited_for=row["cited_for"] or "",
        paragraph_text=row["paragraph_text"] or "",
        location=ClaimLocation.model_validate_json(location) if location else None)
