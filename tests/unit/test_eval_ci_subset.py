"""build_ci_subset.py (FN / FP / stratified controls with eval flags) and ablate_v57.py
(offline replay per disabled proposal). Synthetic rows; no LLM call, no subprocess."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "eval"))

import ablate_v57  # noqa: E402
import build_ci_subset  # noqa: E402
from eval_models import ItemRecord  # noqa: E402

LABELS = {"ACCURATE": "supported", "OVERSIMPLIFY": "partially_supported",
          "ETIQUETTE": "not_supported", "IRRELEVANT": "not_relevant"}


def ci_row(item_id: str, fine: str) -> dict[str, object]:
    gold = LABELS[fine]
    return {"id": item_id, "claim": "c", "source_id": "s", "source_text": "t",
            "gold_label": gold, "gold_binary": "ok" if gold == "supported" else "problem",
            "fine_label": fine, "dataset": "citation_integrity"}


def run_record(row: dict[str, object], verdict: str) -> ItemRecord:
    return ItemRecord.model_validate({**{k: row[k] for k in (
        "id", "dataset", "gold_label", "gold_binary", "fine_label")}, "mode": "cascade",
        "verdict": verdict})


def test_allocate_is_proportional_with_a_floor() -> None:
    assert build_ci_subset.allocate({"A": 50, "B": 30, "C": 2}, 10) == {"A": 6, "B": 3, "C": 1}
    assert sum(build_ci_subset.allocate({"A": 7, "B": 1, "C": 1}, 4).values()) == 4
    assert build_ci_subset.allocate({"A": 2, "B": 1}, 10) == {"A": 2, "B": 1}  # capped
    assert build_ci_subset.allocate({"A": 5, "B": 5, "C": 5}, 2) == {"A": 1, "B": 1, "C": 0}
    assert build_ci_subset.allocate({}, 3) == {}


def test_subset_roles_flags_and_seeded_controls(tmp_path: Path) -> None:
    rows = [ci_row("fn-1", "OVERSIMPLIFY"), ci_row("fn-2", "ETIQUETTE"),
            ci_row("fp-1", "ACCURATE"), ci_row("ok-1", "ACCURATE")]
    rows += [ci_row(f"c-{i}", fine) for i, fine in enumerate(
        ["ACCURATE"] * 6 + ["IRRELEVANT"] * 4 + ["ETIQUETTE"] * 2)]
    verdicts = {"fn-1": "supported", "fn-2": "supported", "fp-1": "partially_supported",
                "ok-1": "supported", "c-0": "cannot_verify"}
    records = {str(r["id"]): run_record(r, verdicts.get(str(r["id"]), "not_relevant"))
               for r in rows}
    subset = build_ci_subset.build_subset(rows, records, 5, 57, {"fn-1"})
    roles = [(r["id"], r["subset_role"]) for r in subset]
    assert roles[:3] == [("fn-1", "fn"), ("fn-2", "fn"), ("fp-1", "fp")]
    controls = [r for r in subset if r["subset_role"] == "control"]
    assert len(controls) == 5 and len({r["fine_label"] for r in controls}) == 3
    assert subset == build_ci_subset.build_subset(rows, records, 5, 57, {"fn-1"})  # seeded
    flags = {r["id"]: r["eval_flags"] for r in subset}
    assert flags["fn-1"] == ["label_noise"] and flags["fn-2"] == ["etiquette"]
    assert subset[0]["ref_verdict"] == "supported" and subset[0]["source_text"] == "t"


def test_cli_writes_subset_and_manifest(tmp_path: Path) -> None:
    rows = [ci_row("fn-1", "OVERSIMPLIFY"), ci_row("ok-1", "ACCURATE"),
            ci_row("ok-2", "IRRELEVANT")]
    data = tmp_path / "ci.jsonl"
    data.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    run = tmp_path / "res" / "ref"
    run.mkdir(parents=True)
    run.joinpath("items.jsonl").write_text("".join(
        run_record(r, "not_relevant" if r["id"] == "ok-2" else "supported").model_dump_json()
        + "\n" for r in rows), encoding="utf-8")
    out = tmp_path / "sub" / "subset.jsonl"
    build_ci_subset.main(["--run", "ref", "--dataset", str(data), "--controls", "1",
                          "--label-noise", "fn-1,missing-id", "--out", str(out),
                          "--results-dir", str(tmp_path / "res")])
    written = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [r["subset_role"] for r in written] == ["fn", "control"]
    info = json.loads(out.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    assert info["by_role"] == {"fn": 1, "control": 1} and info["flags"] == {"label_noise": 1}
    assert info["label_noise_not_in_subset"] == ["missing-id"]


def test_ablation_runs_each_config_with_blank_keys(tmp_path: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], dict[str, str]]] = []
    rec = ItemRecord(id="a", dataset="d", gold_label="supported", gold_binary="ok",
                     mode="cascade", verdict="supported", split="dev")

    def fake_run(cmd: list[str], env: dict[str, str], **kw: object) -> object:
        calls.append((cmd, env))
        out = tmp_path / cmd[cmd.index("--run-name") + 1]
        out.mkdir(parents=True, exist_ok=True)
        out.joinpath("items.jsonl").write_text(rec.model_dump_json() + "\n", encoding="utf-8")
        return type("Done", (), {"returncode": 0})()

    monkeypatch.setattr("ablate_v57.subprocess.run", fake_run)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    results = ablate_v57.main(["--screen-from", "base", "--proposals", "3,5", "--opt-in", "24",
                               "--results-dir", str(tmp_path), "--", "--concurrency", "2"])
    assert list(results) == ["all-on", "no3", "no5", "with24"]
    switches = sorted((env["REFCHECK_V57_DISABLE"], env["REFCHECK_V57_ENABLE"])
                      for _, env in calls)
    assert switches == [("", ""), ("", "24"), ("3", ""), ("5", "")]
    assert all(env["OPENAI_API_KEY"] == "" for _, env in calls)
    cmd = calls[0][0]
    assert "--offline" in cmd and cmd[-2:] == ["--concurrency", "2"]
    assert (tmp_path / "ablate-v57.json").is_file()
