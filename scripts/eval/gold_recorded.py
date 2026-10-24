"""An app run's stored verdicts (verifications table) -> eval ItemRecords (mode "recorded").

Lets the gold benchmark score what the tool actually reported, with no LLM
call. Per-layer outputs come from model_reasoning_json; the verifier/confirm
explanation ends with "[severity S, problem P]" (verifier_converters), and a
later ", partial T" part is read as the layer's partial sub-type. A gold row that merges
several claims of one (sentence, reference) pair is scored on its most severe copy.
"""

import json
import re

from eval_models import ItemRecord, LayerRecord, ScreenRecord
from gold_db import DbVerification, PairKey, SessionData
from gold_models import GoldRow, normalize_sentence
from pydantic import BaseModel, ConfigDict

_TAG_RE = re.compile(r"\[severity (\w+), problem (\w+)(?:, partial(?:_type)? (\w+))?\]")
_ROLES = {"Verifier": "verifier", "Confirm": "confirm", "Judge": "judge"}
# Verdict severity for merged pairs (higher = more severe; unscorable verdicts lowest).
_SEVERITY = {"supported": 1, "partially_supported": 2, "not_relevant": 3,
             "insufficient_evidence": 3, "not_supported": 3, "contradicted": 4}


class StoredReasoning(BaseModel):
    """One ModelReasoning entry as stored in model_reasoning_json."""

    model_config = ConfigDict(extra="ignore")

    model_name: str = ""
    model_display: str = ""
    verdict: str = ""
    confidence: float = 0.0
    reasoning: str = ""
    response_time_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


def parse_tag(reasoning: str) -> tuple[str, str, str]:
    """(severity, problem_type, partial_type) from the explanation tag ("" when absent)."""
    match = _TAG_RE.search(reasoning or "")
    if match is None:
        return "", "", ""
    return match.group(1), match.group(2), match.group(3) or ""


def _entries(raw: str) -> list[StoredReasoning]:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return [StoredReasoning.model_validate(e) for e in data if isinstance(e, dict)]


def _layer(entry: StoredReasoning) -> LayerRecord:
    prefix = entry.model_display.split(" · ")[0]
    role = _ROLES.get(prefix, prefix.lower() or "layer")
    severity, problem, partial = parse_tag(entry.reasoning)
    return LayerRecord(
        layer=role, role=role, model_id=entry.model_name, verdict=entry.verdict or None,
        severity=severity or None, problem_type=problem or None,
        partial_type=partial or None, confidence=entry.confidence,
        latency_ms=entry.response_time_ms, input_tokens=entry.input_tokens,
        output_tokens=entry.output_tokens)


def _label_entry(entries: list[StoredReasoning], verdict: str) -> StoredReasoning | None:
    """The layer whose explanation is shown: last one with the final verdict, else L2."""
    layers = [e for e in entries if not e.model_display.startswith("Decisions")]
    same = [e for e in layers if e.verdict == verdict]
    return same[-1] if same else (layers[0] if layers else None)


def find_verification(row: GoldRow, session: SessionData,
                      index: dict[PairKey, list[int]]) -> DbVerification | None:
    """The session's verdict for the gold pair (matched on sentence + reference). When
    several claims share the pair (a merged gold row), the most severe copy is scored."""
    numbers = index.get((normalize_sentence(row.sentence), row.ref), [])
    found = [v for n in numbers if (v := session.verifications.get((n, row.ref)))]
    if not found:
        return None
    own = [v for v in found if row.session_id == session.session_id
           and v.claim_number == row.claim_number]
    ordered = own + [v for v in found if v not in own]  # ties: the row's own claim first
    return max(ordered, key=lambda v: _SEVERITY.get(v.verdict, 0))


def recorded_record(row: GoldRow, ver: DbVerification | None) -> ItemRecord:
    base = ItemRecord(
        id=row.id, dataset=row.dataset, gold_label=row.gold_label,
        gold_binary=row.gold_binary, fine_label=row.gold_partial_type, mode="recorded",
        gold_partial_type=row.gold_partial_type, tool_misread_type=row.tool_misread_type,
        gold_secondary_types=list(row.secondary_types),
        gold_confidence=row.gold_confidence, split=row.split, gold_source=row.gold_source)
    if ver is None:
        return base.model_copy(update={"error": "pair not in the recorded session"})
    entries = _entries(ver.model_reasoning)
    screen = next((e for e in entries if e.model_display.startswith("Decisions")), None)
    label = _label_entry(entries, ver.verdict)
    severity, problem, partial = parse_tag(label.reasoning) if label else ("", "", "")
    return base.model_copy(update={
        "coverage": ver.coverage, "verdict": ver.verdict,
        "cannot_verify_reason": ver.cannot_verify_reason, "decided_by": ver.decided_by,
        "consensus_type": ver.consensus_type, "layer_path": ver.layer_path,
        "needs_review": ver.needs_review, "cost_usd": ver.cost_usd,
        "latency_ms": ver.latency_ms,
        "layers": [_layer(e) for e in entries if not e.model_display.startswith("Decisions")],
        "screen": ScreenRecord(s=ver.screen_p_support, model=screen.model_name)
        if screen is not None else None,
        "severity": severity, "problem_type": problem,
        "partial_type": ver.partial_type or partial, "guards_applied": ver.guards_applied})
