"""run_eval --screen-from / --offline (eval_cache, eval_recorded): recorded screens, a
cache-only replay, needs_call fallbacks and the key guard. Synthetic rows, no network."""

import json
import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "eval"))

import eval_cache  # noqa: E402
import run_eval  # noqa: E402
from eval_cli import parse_args  # noqa: E402
from eval_models import EvalConfig, ItemRecord, MissedCall, ScreenRecord  # noqa: E402
from eval_recorded import fallback_record, offline_report, recorded_screen  # noqa: E402
from eval_roles import offline_roles  # noqa: E402

from refcheck.llm import keys, structured  # noqa: E402
from refcheck.llm.cache import close_caches  # noqa: E402
from refcheck.llm.completion import CompletionOutcome  # noqa: E402
from refcheck.llm.usage import TokenUsage  # noqa: E402
from refcheck.stages.verify_claims.calibration import ScreenThresholds  # noqa: E402
from tests.unit.verify_fakes import ABSTRACT, FULL_TEXT  # noqa: E402

PROBS = {"topic_match": 0.9, "finding_stated": 0.95, "evidence_sufficient": 0.9,
         "finding_conflicts": 0.0, "claim_overreaches": 0.1, "contains_instructions": 0.0}
ANSWER = json.dumps({"verdict": "supported", "severity": "none", "problem_type": "none",
                     "confidence": 0.9, "quotes": [], "explanation": "Stated in [P1].",
                     "missing": None})


def row(item_id: str, claim: str, flags: list[str] | None = None) -> dict[str, object]:
    return {"id": item_id, "claim": claim, "source_id": f"S-{item_id}",
            "source_title": "Drug X", "source_text": FULL_TEXT, "source_abstract": ABSTRACT,
            "gold_label": "supported", "gold_binary": "ok", "fine_label": "ACCURATE",
            "dataset": "synthetic_ci", "split": "test", "eval_flags": flags or []}


def reference_record(item_id: str, verdict: str) -> ItemRecord:
    return ItemRecord(id=item_id, dataset="synthetic_ci", gold_label="supported",
                      gold_binary="ok", mode="cascade", verdict=verdict,
                      screen=ScreenRecord(probs=PROBS, s=0.9, model="gpt-6-luna-decisions",
                                          cost_usd=0.0004, latency_ms=200))


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Own cache dir, every key env var restored afterwards, no .env, adjudicator off."""
    for name in eval_cache.key_env_names():
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("REFCHECK_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("REFCHECK_ADJUDICATE", "off")
    monkeypatch.setattr(run_eval, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(run_eval, "load_thresholds",
                        lambda: ScreenThresholds(t_accept=1.0, auto_clear=False))
    data = tmp_path / "rows.jsonl"
    data.write_text("".join(json.dumps(r) + "\n" for r in [
        row("ci-a", "Drug X reduced IL-6 levels by 40% in mice."),
        row("ci-b", "Drug X reduced body weight in mice.", ["label_noise"])]),
        encoding="utf-8")
    ref = tmp_path / "res" / "ref"
    ref.mkdir(parents=True)
    ref.joinpath("items.jsonl").write_text(
        reference_record("ci-a", "supported").model_dump_json() + "\n"
        + reference_record("ci-b", "partially_supported").model_dump_json() + "\n",
        encoding="utf-8")
    yield tmp_path
    close_caches()
    keys.reset_keys()


def config(base: Path, *extra: str) -> EvalConfig:
    return parse_args(["--dataset", str(base / "rows.jsonl"), "--mode", "cascade",
                       "--no-embeddings", "--results-dir", str(base / "res"),
                       "--screen-from", "ref", *extra])


async def record_cache(base: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A 'live' run of ci-a only whose fake provider fills the cache."""
    sent: list[str] = []

    async def fake_complete(spec: object, messages: object, *a: object,
                            **k: object) -> CompletionOutcome:
        sent.append(str(k.get("role")))
        return CompletionOutcome(content=ANSWER, usage=TokenUsage(input_tokens=10,
                                 output_tokens=5), latency_ms=3, finish_reason="stop")

    async def roles_without_preflight(cfg: EvalConfig, thresholds: ScreenThresholds,
                                      tracker: object) -> object:
        return offline_roles(cfg, thresholds)

    with monkeypatch.context() as m:
        m.setattr(structured, "complete", fake_complete)
        m.setattr(keys, "has_key", lambda provider: True)
        m.setattr(run_eval, "check_roles", roles_without_preflight)
        summary = await run_eval.run(config(base, "--reuse-cache", "--limit", "1",
                                            "--run-name", "rec"))
    assert summary.headline.n == 1 and sent and "screen" not in sent


async def test_offline_replay_hits_the_cache_and_falls_back_on_misses(
        sandbox: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    await record_cache(sandbox, monkeypatch)
    summary = await run_eval.run(config(sandbox, "--offline", "--run-name", "off"))
    lines = (sandbox / "res" / "off" / "items.jsonl").read_text(encoding="utf-8")
    recs = {r.id: r for r in map(ItemRecord.model_validate_json, lines.splitlines())}
    own, missed = recs["ci-a"], recs["ci-b"]
    assert not own.needs_call and own.verdict == "supported" and own.cost_usd == 0.0
    assert own.screen is not None and own.screen.probs == PROBS and own.screen.cost_usd == 0.0
    assert own.layers and all(lay.cached for lay in own.layers)
    assert missed.needs_call and missed.verdict == "partially_supported"  # from "ref"
    assert missed.eval_flags == ["label_noise"] and missed.split == "test"
    assert missed.missed_calls[0].kind == "chat" and missed.missed_calls[0].est_cost_usd > 0
    assert summary.meta.offline and summary.meta.fallback_from == "ref"
    assert summary.offline is not None and summary.offline.pairs_needing_calls == 1
    assert summary.offline.calls_by_role.get("chat:verifier", 0) >= 1
    assert summary.headline.hygiene is not None and summary.headline.hygiene.needs_call == 1
    assert {"clean", "flag:label_noise", "split:test"} <= set(summary.groups)
    assert keys.has_key("openai") is False  # the patch is gone and the keys stay blank


async def test_offline_refuses_unsafe_runs(sandbox: Path,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    no_screen = parse_args(["--dataset", str(sandbox / "rows.jsonl"), "--offline",
                            "--results-dir", str(sandbox / "res")])
    with pytest.raises(SystemExit, match="screen-from"):
        await run_eval.run(no_screen)
    with pytest.raises(SystemExit, match="dry-run"):
        eval_cache.check_offline(config(sandbox, "--offline").model_copy(
            update={"dry_run": True}), True)
    monkeypatch.setattr(keys, "key_count", lambda provider: 1)
    with pytest.raises(SystemExit, match="keys still visible"):
        eval_cache.check_offline(config(sandbox, "--offline"), True)


def test_check_offline_blanks_every_key(sandbox: Path,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    monkeypatch.setenv("ANTHROPIC_API_KEY_BACKUP", "sk-ant-test")
    monkeypatch.setenv("SOME_SERVICE_API_KEY", "x")
    eval_cache.check_offline(config(sandbox, "--offline"), True)
    assert eval_cache.visible_keys() == []
    assert os.environ["OPENAI_API_KEY"] == "" and os.environ["SOME_SERVICE_API_KEY"] == ""


def test_cli_flags_and_recorded_screen() -> None:
    cfg = parse_args(["--offline", "--screen-from", "a", "--fallback-from", "b"])
    assert cfg.offline and cfg.reuse_cache and (cfg.screen_from, cfg.fallback_from) == ("a", "b")
    with pytest.raises(SystemExit):
        parse_args(["--fallback-from", "b"])
    result = recorded_screen(ScreenRecord(probs=PROBS, s=0.7, model="gpt-6-luna-decisions",
                                          cost_usd=0.1, latency_ms=50))
    assert result.ok and result.p_problem == 0.3 and result.cost_usd == 0.0
    failed = recorded_screen(ScreenRecord(error="timeout", model=""))
    assert not failed.ok and failed.p_problem is None


def test_fallback_record_keeps_current_gold_and_reports_cost() -> None:
    current = ItemRecord(id="x", dataset="d", gold_label="partially_supported",
                         gold_binary="problem", mode="cascade", split="dev",
                         eval_flags=["etiquette"], verdict="cannot_verify")
    ref = ItemRecord(id="x", dataset="d", gold_label="supported", gold_binary="ok",
                     mode="cascade", verdict="supported", needs_review=True, cost_usd=0.01)
    miss = MissedCall(kind="chat", role="adjudicator", model="m", est_cost_usd=0.002)
    rec = fallback_record(current, ref, [miss])
    assert (rec.verdict, rec.gold_label, rec.split, rec.eval_flags) == (
        "supported", "partially_supported", "dev", ["etiquette"])
    assert rec.needs_call and rec.needs_review and rec.cost_usd == 0.0
    orphan = fallback_record(current, None, [miss])
    assert orphan.verdict == "error" and orphan.error and "needs_call" in orphan.error
    report = offline_report([rec, orphan], [MissedCall(kind="embedding", est_cost_usd=0.001)])
    assert report.pairs_needing_calls == 2 and report.pairs_without_fallback == 1
    assert report.calls_by_role == {"chat:adjudicator": 2, "embedding:-": 1}
    assert report.est_cost_usd == pytest.approx(0.005) and report.setup_calls == 1


async def test_cache_only_stand_ins_record_misses_per_pair() -> None:
    from refcheck.llm.errors import LLMCallError
    from refcheck.llm.model_lookup import spec_for

    misses = eval_cache.item_misses()
    spec = spec_for("claude-haiku-5-5")
    with pytest.raises(LLMCallError) as err:
        await eval_cache.cache_only_complete(spec, [{"role": "user", "content": "x" * 400}],
                                             None, role="verifier")
    assert not err.value.is_hard  # never benches the model
    with pytest.raises(LLMCallError):
        await eval_cache.cache_only_decide()
    assert [(m.kind, m.role) for m in misses] == [("chat", "verifier"), ("screen", "screen")]
    assert misses[0].est_input_tokens == 100 and misses[1].est_cost_usd > 0
