"""Unit tests for compare_models.py / eval_report.py (Pareto table; runs are faked)."""

import argparse
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "eval"))

import compare_models  # noqa: E402
from eval_metrics import MetricBlock, RunSummary  # noqa: E402
from eval_models import EvalConfig, RunMeta  # noqa: E402
from eval_report import pareto_flags, summary_lines, table  # noqa: E402
from eval_stats import BinaryMetrics  # noqa: E402


def summary(name: str, acc: float, cost: float, p50: float) -> RunSummary:
    meta = RunMeta(run_name=name, mode="verifier", dataset="smoke", split="dev",
                   dataset_path="x", n_items=10, source="auto", use_embeddings=True,
                   concurrency=1, started_at="now", roles={"verifier": name})
    head = MetricBlock(n=10, n_scored=10, n_errors=0, accuracy_6way=acc, macro_f1=acc / 2,
                       problem=BinaryMetrics(f1=0.5, recall=0.6), cost_per_1k_pairs=cost,
                       latency_p50_ms=p50, latency_p90_ms=2 * p50)
    return RunSummary(meta=meta, headline=head)


def test_parse_candidates_with_and_without_effort() -> None:
    cands = compare_models.parse_candidates("gpt-6-luna:none, claude-haiku-5-5 ,")
    assert [(c.model, c.effort) for c in cands] == [("gpt-6-luna", "none"),
                                                   ("claude-haiku-5-5", None)]
    assert cands[0].label == "gpt-6-luna:none" and cands[1].label == "claude-haiku-5-5"


def test_pareto_flags_drop_dominated_points() -> None:
    points = [(0.8, 1.0, 100.0), (0.7, 2.0, 200.0), (0.9, 10.0, 100.0), (0.8, 1.0, 100.0)]
    assert pareto_flags(points) == [True, False, True, True]


def test_table_is_aligned() -> None:
    lines = table(["a", "bbb"], [["xx", "1"], ["y", "22"]])
    assert lines[0] == "a   bbb" and lines[1] == "--  ---" and lines[2] == "xx  1  "


def test_summary_lines_mention_headline_and_cache_note() -> None:
    s = summary("m", 0.8, 1.0, 100.0)
    s.headline.cached_layer_calls = 3
    text = "\n".join(summary_lines(s))
    assert "HEADLINE" in text and "acc6=80.0%" in text and "LLM cache" in text
    assert "to-judge" not in text  # routing rates are cascade-only


def test_summary_lines_show_v51_routing_for_cascade() -> None:
    s = summary("m", 0.8, 1.0, 100.0)
    s.headline.escalation_rate, s.headline.cross_check_rate = 0.05, 0.4
    s.headline.consensus = {"confirmed": 3, "disputed": 1}
    text = "\n".join(summary_lines(s))
    assert "to-judge=5.0% cross-checked=40.0% disputed=1" in text
    assert "consensus: {'confirmed': 3, 'disputed': 1}" in text


async def test_compare_runs_each_candidate_and_marks_pareto(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: list[EvalConfig] = []
    results = {"a": (0.8, 1.0, 100.0), "b": (0.7, 2.0, 300.0), "c": (0.9, 5.0, 900.0)}

    async def fake_run(cfg: EvalConfig) -> RunSummary:
        seen.append(cfg)
        return summary(cfg.models["verifier"], *results[cfg.models["verifier"]])

    monkeypatch.setattr(compare_models, "run", fake_run)
    monkeypatch.setattr(compare_models, "RESULTS_DIR", tmp_path)
    monkeypatch.setenv("REFCHECK_VERIFIER_EFFORT", "high")
    args = argparse.Namespace(role="verifier", candidates="a:low,b,c:none", dataset="smoke",
                              split="dev", limit=5, concurrency=2, skip_synthetic=False,
                              max_cost=1.0, reuse_cache=False)
    rows = await compare_models.compare(args)
    assert [r.candidate for r in rows] == ["a:low", "b", "c:none"]
    assert [r.pareto for r in rows] == [True, False, True]
    assert all(cfg.mode == "verifier" and not cfg.with_screen for cfg in seen)
    assert seen[0].efforts == {"verifier": "low"} and seen[1].efforts == {}
    assert "REFCHECK_VERIFIER_EFFORT" not in os.environ  # no effort leaks between candidates
    assert len(list(tmp_path.glob("compare-*-verifier.json"))) == 1
