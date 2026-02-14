"""Database persistence helpers for the pipeline runner."""

import json

from refcheck.db.converters import (
    claim_to_db,
    reference_to_db,
    verification_to_db,
)
from refcheck.db.engine import get_db_session
from refcheck.db.session_repo import update_session
from refcheck.models.claim import Claim
from refcheck.models.reference import ManuscriptSection, Reference
from refcheck.models.verification import VerificationResult


def persist_references(session_id: str, refs: list[Reference]) -> None:
    """Save references to the database."""
    from refcheck.db.reference_repo import save_references

    db = get_db_session()
    try:
        db_refs = [reference_to_db(r, session_id) for r in refs]
        save_references(db, session_id, db_refs)
    finally:
        db.close()


def persist_claims(session_id: str, claims: list[Claim]) -> None:
    """Save claims to the database."""
    from refcheck.db.claim_repo import save_claims

    db = get_db_session()
    try:
        db_claims = [claim_to_db(c, session_id) for c in claims]
        save_claims(db, session_id, db_claims)
    finally:
        db.close()


def persist_verifications(
    session_id: str, verifications: list[VerificationResult],
) -> None:
    """Save verifications to the database."""
    from refcheck.db.verification_repo import save_verifications

    db = get_db_session()
    try:
        db_vs = [verification_to_db(v, session_id) for v in verifications]
        save_verifications(db, session_id, db_vs)
    finally:
        db.close()


def update_stage(session_id: str, stage: int) -> None:
    """Update the current stage in the database."""
    db = get_db_session()
    try:
        update_session(db, session_id, current_stage=stage)
    finally:
        db.close()


def persist_manuscript_sections(
    session_id: str, sections: list[ManuscriptSection],
) -> None:
    """Store manuscript sections JSON for the viewer."""
    sections_json = json.dumps([s.model_dump() for s in sections])
    db = get_db_session()
    try:
        update_session(db, session_id, manuscript_sections_json=sections_json)
    finally:
        db.close()


def persist_report_path(session_id: str, report_path: str) -> None:
    """Store the report file path in the database."""
    db = get_db_session()
    try:
        update_session(db, session_id, report_path=report_path)
    finally:
        db.close()
