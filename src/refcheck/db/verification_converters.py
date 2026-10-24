"""Convert VerificationResult <-> VerificationDB.

Reading is NULL-safe: columns added by ALTER TABLE migrations read back as
NULL on rows written before the migration, and those rows must still load
with the model defaults instead of failing validation.
"""

import json
import logging
from typing import TypeVar, get_args

from pydantic import BaseModel

from refcheck.db.models import VerificationDB
from refcheck.models.evidence import EvidenceSection
from refcheck.models.partial_types import PartialSeverity
from refcheck.models.verification import (
    AtomicVerification,
    DecidedBy,
    ModelReasoning,
    VerificationResult,
    VoteRecord,
)

logger = logging.getLogger(__name__)

__all__ = ["db_to_verification", "load_json_list", "or_default", "verification_to_db"]

T = TypeVar("T")
M = TypeVar("M", bound=BaseModel)

_DECIDED_BY: frozenset[str] = frozenset(get_args(DecidedBy))
_SEVERITIES: frozenset[str] = frozenset(get_args(PartialSeverity))


def or_default(value: T | None, default: T) -> T:
    """``default`` when a (pre-migration) column is NULL."""
    return default if value is None else value


def load_json_list(raw: str | None, column: str = "") -> list[object]:
    """Parse a JSON list column; NULL, empty or corrupt values give []."""
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Ignoring corrupt JSON in column %s", column or "?")
        return []
    return list(value) if isinstance(value, list) else []


def _dump_models(items: list[M] | None) -> str | None:
    if not items:
        return None
    return json.dumps([item.model_dump(mode="json") for item in items])


def _load_models(raw: str | None, model: type[M], column: str) -> list[M]:
    return [model.model_validate(item) for item in load_json_list(raw, column)
            if isinstance(item, dict)]


def verification_to_db(v: VerificationResult, session_id: str) -> VerificationDB:
    """Convert a Pydantic VerificationResult to a VerificationDB row."""
    return VerificationDB(
        session_id=session_id,
        claim_id=v.claim_id,
        reference_id=v.reference_id,
        verdict=v.verdict,
        confidence=v.confidence,
        evidence_quotes_json=json.dumps(v.evidence_quotes),
        reasoning=v.reasoning,
        tier=v.tier,
        source_coverage=v.source_coverage,
        needs_user_review=v.needs_user_review,
        user_override=v.user_override,
        user_override_reason=v.user_override_reason,
        original_verdict=v.original_verdict,
        original_confidence=v.original_confidence,
        atomic_results_json=(json.dumps([a.model_dump() for a in v.atomic_results])
                             if v.atomic_results is not None else None),
        evidence_sections_json=_dump_models(v.evidence_sections),
        model_reasoning_json=_dump_models(v.model_reasoning),
        cannot_verify_reason=v.cannot_verify_reason,
        section_relevance=v.section_relevance,
        text_quality_score=v.text_quality_score,
        retry_strategy_used=v.retry_strategy_used,
        retry_attempts=v.retry_attempts,
        votes_json=_dump_models(v.votes),
        consensus_type=v.consensus_type,
        final_tier=v.final_tier,
        escalation_path_json=json.dumps(v.escalation_path),
        total_models_consulted=v.total_models_consulted,
        agreement_ratio=v.agreement_ratio,
        decided_by=v.decided_by,
        screen_p_support=v.screen_p_support,
        screen_p_contradict=v.screen_p_contradict,
        screen_p_topic=v.screen_p_topic,
        layer_path_json=json.dumps(v.layer_path),
        cost_usd=v.cost_usd,
        latency_ms=v.latency_ms,
        quotes_validated=v.quotes_validated,
        partial_type=v.partial_type,
        partial_severity=v.partial_severity,
        author_action=v.author_action,
        unsupported_elements_json=json.dumps(v.unsupported_elements),
        guards_applied_json=json.dumps(v.guards_applied),
    )


def _str_list(raw: str | None, column: str) -> list[str]:
    return [str(item) for item in load_json_list(raw, column) if isinstance(item, str)]


def _partial_type(raw: str | None) -> str | None:
    """None for NULL / "" / "none" (no genuine type)."""
    return raw if raw and raw != "none" else None


def _severity(raw: str | None) -> PartialSeverity | None:
    if raw is None or raw == "":
        return None
    if raw not in _SEVERITIES:
        logger.warning("Unknown partial_severity %r in DB; using None", raw)
        return None
    return raw  # type: ignore[return-value]  # membership checked above


def _decided_by(raw: str | None) -> DecidedBy:
    value = raw or "none"
    if value not in _DECIDED_BY:
        logger.warning("Unknown decided_by %r in DB; using 'none'", value)
        return "none"
    return value  # type: ignore[return-value]  # membership checked above


def db_to_verification(db_v: VerificationDB) -> VerificationResult:
    """Convert a VerificationDB row to a Pydantic VerificationResult."""
    atomic_results = None
    if db_v.atomic_results_json:
        atomic_results = _load_models(db_v.atomic_results_json, AtomicVerification,
                                      "atomic_results_json")
    return VerificationResult(
        claim_id=db_v.claim_id,
        reference_id=db_v.reference_id,
        verdict=db_v.verdict,  # type: ignore[arg-type]
        confidence=db_v.confidence,
        evidence_quotes=[str(q) for q in load_json_list(db_v.evidence_quotes_json)],
        reasoning=db_v.reasoning,
        tier=db_v.tier,
        source_coverage=db_v.source_coverage,  # type: ignore[arg-type]
        needs_user_review=db_v.needs_user_review,
        user_override=db_v.user_override,
        user_override_reason=db_v.user_override_reason,
        original_verdict=db_v.original_verdict,  # type: ignore[arg-type]
        original_confidence=db_v.original_confidence,
        atomic_results=atomic_results,
        evidence_sections=_load_models(db_v.evidence_sections_json, EvidenceSection,
                                       "evidence_sections_json"),
        model_reasoning=_load_models(db_v.model_reasoning_json, ModelReasoning,
                                     "model_reasoning_json"),
        cannot_verify_reason=db_v.cannot_verify_reason,
        section_relevance=or_default(db_v.section_relevance, "high"),
        text_quality_score=or_default(db_v.text_quality_score, 1.0),
        retry_strategy_used=db_v.retry_strategy_used,
        retry_attempts=or_default(db_v.retry_attempts, 0),
        votes=_load_models(db_v.votes_json, VoteRecord, "votes_json"),
        consensus_type=or_default(db_v.consensus_type, ""),
        final_tier=or_default(db_v.final_tier, 0),
        escalation_path=[int(t) for t in load_json_list(db_v.escalation_path_json)
                         if isinstance(t, int)],
        total_models_consulted=or_default(db_v.total_models_consulted, 0),
        agreement_ratio=or_default(db_v.agreement_ratio, 0.0),
        decided_by=_decided_by(db_v.decided_by),
        screen_p_support=db_v.screen_p_support,
        screen_p_contradict=db_v.screen_p_contradict,
        screen_p_topic=db_v.screen_p_topic,
        layer_path=[str(p) for p in load_json_list(db_v.layer_path_json)],
        cost_usd=or_default(db_v.cost_usd, 0.0),
        latency_ms=or_default(db_v.latency_ms, 0),
        quotes_validated=db_v.quotes_validated,
        partial_type=_partial_type(db_v.partial_type),
        partial_severity=_severity(db_v.partial_severity),
        author_action=or_default(db_v.author_action, ""),
        unsupported_elements=_str_list(db_v.unsupported_elements_json,
                                       "unsupported_elements_json"),
        guards_applied=_str_list(db_v.guards_applied_json, "guards_applied_json"),
    )
