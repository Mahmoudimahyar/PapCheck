"""Unit tests for scoring an app run's recorded verdicts on gold rows (synthetic DB)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "eval"))

import score_recorded  # noqa: E402
from gold_db import load_session  # noqa: E402
from gold_models import GoldRow, pair_id  # noqa: E402
from gold_recorded import find_verification, parse_tag, recorded_record  # noqa: E402

from tests.unit.test_eval_gold_build import S1, S2, S3, SESSION, make_db  # noqa: E402


def row(sentence: str, ref: int, label: str, claim_number: int = 0, **extra: object) -> GoldRow:
    base: dict[str, object] = {
        "id": pair_id(sentence, ref), "session_id": SESSION, "claim_number": claim_number,
        "sentence": sentence, "claim": sentence, "ref": ref, "gold_label": label,
        "gold_binary": "ok" if label == "supported" else "problem", "gold_source": "review_B"}
    base.update(extra)
    return GoldRow.model_validate(base)


def test_parse_tag() -> None:
    assert parse_tag("x [severity minor, problem overgeneralized]") == (
        "minor", "overgeneralized", "")
    assert parse_tag("[severity major, problem compound_part_only, partial co_cited_share]") \
        == ("major", "compound_part_only", "co_cited_share")
    assert parse_tag("no tag") == ("", "", "")


def test_recorded_record_reads_layers_and_classification(tmp_path: Path) -> None:
    session = load_session(SESSION, make_db(tmp_path / "db.sqlite"))
    index = session.pair_index()
    gold = row("  " + S1.upper(), 1, "supported", tool_misread_type="over_literal")
    ver = find_verification(gold, session, index)
    rec = recorded_record(gold, ver)
    assert ver is not None and rec.mode == "recorded"
    assert rec.verdict == "partially_supported" and rec.decided_by == "verifier"
    assert (rec.severity, rec.problem_type) == ("minor", "overgeneralized")
    assert [lay.role for lay in rec.layers] == ["verifier"]
    assert rec.screen is not None and rec.screen.s == 0.2
    assert rec.tool_misread_type == "over_literal" and rec.layer_path == ["screen", "verifier"]
    missing = recorded_record(row("Unknown sentence.", 1, "supported"),
                              find_verification(row("Unknown sentence.", 1, "supported"),
                                                session, index))
    assert missing.error == "pair not in the recorded session"


def test_score_recorded_cli_writes_summary_and_splits(tmp_path: Path) -> None:
    db = make_db(tmp_path / "db.sqlite")
    rows = [row(S1, 1, "supported", 1, split="dev"),
            row(S2, 3, "partially_supported", 3, split="test", gold_partial_type="scope"),
            row(S3, 4, "supported", 4, split="test"),
            row("Excluded (X).", 4, "cannot_judge", exclude=True)]
    data = tmp_path / "gold.jsonl"
    data.write_text("".join(r.model_dump_json() + "\n" for r in rows), encoding="utf-8")
    summary = score_recorded.run(score_recorded.parse_args([
        "--dataset", str(data), "--session", SESSION, "--db", str(db),
        "--results-dir", str(tmp_path / "res"), "--run-name", "base"]))
    out = tmp_path / "res" / "base"
    assert summary.headline.n == 3 and summary.headline.n_errors == 0
    partial = summary.headline.partial
    assert partial is not None and partial.over_harsh == "1/2"
    assert partial.by_gold_partial_type == {"scope": {"partial": 1}}
    assert (out / "items.jsonl").read_text(encoding="utf-8").count("\n") == 3
    splits = json.loads((out / "by_split.json").read_text(encoding="utf-8"))["blocks"]
    assert splits["dev"]["n"] == 1 and splits["test"]["n"] == 2
    meta = json.loads((out / "summary.json").read_text(encoding="utf-8"))["meta"]
    assert meta["mode"] == "recorded" and meta["roles"] == {"verifier": "verifier-model"}
