"""Unit tests for the partial-verdict metrics (3-way, harshness, sub-type confusions)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "eval"))

from eval_clearance import auto_cleared  # noqa: E402
from eval_metrics import compute_block, summarize  # noqa: E402
from eval_models import ItemRecord, RunMeta  # noqa: E402
from eval_partial import compute_partial, partial_line, three_way, type_matches  # noqa: E402
from eval_report import summary_lines  # noqa: E402


def rec(gold: str, verdict: str, *, severity: str = "", gold_type: str = "",
        tool_type: str = "", misread: str = "", cv: str | None = None,
        confidence: str = "high", mode: str = "cascade") -> ItemRecord:
    return ItemRecord(
        id=f"{gold}-{verdict}-{gold_type}-{tool_type}-{severity}", dataset="refcheck_v49_gold",
        gold_label=gold, gold_binary="ok" if gold == "supported" else "problem",
        mode=mode, verdict=verdict, cannot_verify_reason=cv,  # type: ignore[arg-type]
        decided_by="verifier", severity=severity, gold_partial_type=gold_type,
        partial_type=tool_type, tool_misread_type=misread, gold_confidence=confidence)


RECORDS = [
    rec("supported", "partially_supported", severity="minor", misread="over_literal"),
    rec("supported", "supported", confidence="medium"),
    rec("partially_supported", "partially_supported", severity="major",
        gold_type="co_cited_share", tool_type="co_cited_share"),
    rec("partially_supported", "supported", gold_type="overgeneralized_scope"),
    rec("not_supported", "supported"),
    rec("contradicted", "insufficient_evidence"),
    rec("partially_supported", "cannot_verify", cv="llm_error"),
    rec("partially_supported", "partially_supported", severity="minor",
        gold_type="numeric_detail", tool_type="co_cited_share"),
]


def test_three_way_mapping() -> None:
    assert three_way("not_relevant") == three_way("contradicted") == "negative"
    assert three_way("partially_supported") == "partial" and three_way("error") is None


def test_unresolvable_evidence_gap_matches_coverage_limited() -> None:
    assert type_matches("evidence_gap", "coverage_limited")
    assert type_matches("coverage_limited", "evidence_gap")  # one type either way (#12)
    assert not type_matches("missing_element", "coverage_limited")
    m = compute_partial([rec("partially_supported", "partially_supported",
                             gold_type="evidence_gap", tool_type="coverage_limited")])
    assert m is not None and m.partial_type_accuracy == pytest.approx(1.0)
    assert (m.partial_type_flagged, m.partial_type_accuracy_flagged) == ("1/1", 1.0)

def test_partial_metrics_rates_and_confusions() -> None:
    m = compute_partial(RECORDS)
    assert m is not None and m.n_scored == 7
    assert m.accuracy_3way == pytest.approx(4 / 7)
    assert (m.over_harsh, m.missed_problem, m.missed_partial) == ("1/2", "1/2", "1/3")
    assert m.confusion_3way["negative"] == {"negative": 1, "supported": 1}
    assert m.by_gold_partial_type == {"co_cited_share": {"partial": 1},
                                      "numeric_detail": {"partial": 1},
                                      "overgeneralized_scope": {"supported": 1}}
    assert m.partial_type_confusion == {"co_cited_share": {"co_cited_share": 1},
                                        "numeric_detail": {"co_cited_share": 1}}
    assert m.partial_type_accuracy == pytest.approx(0.5)
    assert m.misread_flagged == {"over_literal": "1/1"}
    assert m.accuracy_3way_by_confidence["medium"] == pytest.approx(1.0)
    assert m.tool_problem_by_gold["supported"] == {"?/minor": 1}


def test_minor_as_supported_counterfactual() -> None:
    m = compute_partial(RECORDS)
    assert m is not None and m.whatif_minor_as_supported is not None
    whatif = m.whatif_minor_as_supported
    assert whatif.accuracy_3way == pytest.approx(4 / 7)
    assert whatif.over_harsh_rate == pytest.approx(0.0)
    assert whatif.missed_partial_rate == pytest.approx(2 / 3)


def test_nothing_scorable_gives_none() -> None:
    assert compute_partial([rec("supported", "cannot_verify", cv="pdf_scanned")]) is None
    assert partial_line(None) == "3-way: -"


def test_block_and_report_include_partial_metrics() -> None:
    block = compute_block(RECORDS, None)
    assert block.partial is not None and block.partial.over_harsh == "1/2"
    meta = RunMeta(run_name="t", mode="recorded", dataset="g", split="all", dataset_path="x",
                   n_items=len(RECORDS), source="auto", use_embeddings=False, concurrency=0,
                   started_at="now")
    lines = summary_lines(summarize(RECORDS, meta))
    assert any(line.startswith("3-way acc=57.1% (n=7) | over-harsh 1/2") for line in lines)
    assert any("if minor->supported" in line for line in lines)


def test_recorded_mode_counts_screen_decisions_as_auto_clear() -> None:
    cleared = rec("supported", "supported", mode="recorded").model_copy(
        update={"decided_by": "screen"})
    assert auto_cleared(cleared, None) is True
    assert auto_cleared(rec("supported", "supported", mode="recorded"), None) is False


def _guarded(gold: str, verdict: str, guards: list[str], coverage: str = "full_text",
             **kw: str) -> ItemRecord:
    return rec(gold, verdict, **kw).model_copy(update={"guards_applied": guards,
                                                       "coverage": coverage})


def test_partial_type_and_guard_metrics() -> None:
    records = [
        _guarded("supported", "supported", ["evidence_recheck"], misread="evidence_gap"),
        _guarded("supported", "supported", ["overliteral_wording"], misread="evidence_gap"),
        _guarded("supported", "partially_supported", [], "abstract_only",
                 misread="cocited_share"),
        _guarded("supported", "supported", ["cocited_share"]),
        _guarded("partially_supported", "partially_supported", ["author_framing_or_example"],
                 gold_type="missing_element", tool_type="missing_element"),
        _guarded("partially_supported", "not_supported", [], gold_type="unsupported_inference",
                 tool_type="tangential_source"),
    ]
    m = compute_partial(records)
    assert m is not None
    assert (m.partial_type_flagged, m.partial_type_accuracy_flagged) == ("1/2", 0.5)
    assert m.gold_supported_cleared == "3/4"
    assert m.cleared_by_misread == {"cocited_share": "0/1", "evidence_gap": "2/2"}
    assert m.misread_cleared_any == {"cocited_share": "0/1", "evidence_gap": "2/2"}
    assert m.misread_guard_hit == {"cocited_share": "0/1", "evidence_gap": "1/2"}
    assert m.guards_fired == {"author_framing_or_example": 1, "cocited_share": 1,
                              "evidence_recheck": 1, "overliteral_wording": 1}
    assert m.guards_by_gold["partial"] == {"author_framing_or_example": 1}
    line = partial_line(m)
    assert "type acc (flagged) 1/2=50.0%" in line and "gold-supported cleared 3/4" in line
    assert "guards author_framing_or_example=1" in line


def test_evidence_gap_guard_hit_counts_only_full_texts_cleared_by_the_recheck() -> None:
    records = [
        _guarded("supported", "supported", ["evidence_recheck"], misread="evidence_gap"),
        _guarded("supported", "supported", [], misread="evidence_gap"),  # cleared otherwise
        # A partial that kept the guard (part of the concern cleared) is not a clearance.
        _guarded("supported", "partially_supported", ["evidence_recheck"],
                 misread="evidence_gap"),
        # Abstract only: the re-check can never run, so not in the guard's denominator.
        _guarded("supported", "partially_supported", [], "abstract_only",
                 misread="evidence_gap"),
        _guarded("supported", "supported", [], "abstract_only", misread="evidence_gap"),
    ]
    m = compute_partial(records)
    assert m is not None
    assert m.cleared_by_misread == {"evidence_gap": "3/5"}  # any path, all pairs
    assert m.misread_cleared_any == {"evidence_gap": "2/3"}  # any path, full texts
    assert m.misread_guard_hit == {"evidence_gap": "1/3"}  # this guard, full texts
