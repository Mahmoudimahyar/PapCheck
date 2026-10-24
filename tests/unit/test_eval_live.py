"""run_eval --offline --live-roles (eval_live): live chat calls for the listed roles only,
through the kept key, written to the cache; --live-check and the --max-cost cap send
nothing. Fake provider (completion._sync_completion), no network."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "eval"))

import eval_cache  # noqa: E402
import eval_live  # noqa: E402
import run_eval  # noqa: E402
from eval_cli import parse_args  # noqa: E402
from eval_models import ItemRecord  # noqa: E402

from refcheck.llm import completion, keys  # noqa: E402
from refcheck.llm.completion import CompletionOutcome  # noqa: E402
from refcheck.llm.cost_tracker import CostTracker  # noqa: E402
from refcheck.llm.errors import LLMCallError  # noqa: E402
from refcheck.llm.model_lookup import spec_for  # noqa: E402
from refcheck.llm.roles import reset_availability  # noqa: E402
from refcheck.llm.usage import TokenUsage  # noqa: E402
from tests.unit.test_eval_replay import (  # noqa: E402, F401 - sandbox is a fixture
    ANSWER,
    config,
    record_cache,
    sandbox,
)

PRIMARY, BACKUP, OPENAI = "sk-ant-exhausted-test", "sk-ant-backup-test", "sk-openai-test"
Sent = list[tuple[str, str]]


def fake_provider(sent: Sent) -> object:
    """completion._sync_completion stand-in: records (model, api key), answers."""
    def call(kwargs: dict[str, object]) -> object:
        sent.append((str(kwargs["model"]), str(kwargs["api_key"])))
        probe = '{"ok": true}' in str(kwargs["messages"])
        message = SimpleNamespace(content='{"ok": true}' if probe else ANSWER, refusal=None)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message, finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=100))
    return call


def records(base: Path, run: str) -> dict[str, ItemRecord]:
    lines = (base / "res" / run / "items.jsonl").read_text(encoding="utf-8").splitlines()
    return {r.id: r for r in map(ItemRecord.model_validate_json, lines)}


@pytest.fixture
def live_env(sandbox: Path, monkeypatch: pytest.MonkeyPatch) -> Path:  # noqa: F811
    monkeypatch.setenv("REFCHECK_KEY_STATE_FILE", "")
    monkeypatch.setenv("REFCHECK_LLM_MAX_ATTEMPTS", "1")
    for name in [n for n in os.environ if n.startswith("REFCHECK_") and n.endswith(
            ("_MODEL", "_EFFORT"))]:  # role overrides other tests' runs left behind
        monkeypatch.delenv(name)
    reset_availability()
    return sandbox


async def test_live_role_uses_only_the_kept_key_and_fills_the_cache(
        live_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    await record_cache(live_env, monkeypatch)  # ci-a cached, ci-b not
    for name, value in (("ANTHROPIC_API_KEY", PRIMARY), ("ANTHROPIC_API_KEY_BACKUP", BACKUP),
                        ("OPENAI_API_KEY", OPENAI)):
        monkeypatch.setenv(name, value)
    sent: Sent = []
    monkeypatch.setattr(completion, "_sync_completion", fake_provider(sent))
    summary = await run_eval.run(config(
        live_env, "--offline", "--live-roles", "verifier", "--live-keys",
        "ANTHROPIC_API_KEY_BACKUP", "--max-cost", "1", "--run-name", "live"))
    assert sent and all(s == ("anthropic/claude-haiku-5-5", BACKUP) for s in sent)
    assert os.environ["ANTHROPIC_API_KEY"] == "" and os.environ["OPENAI_API_KEY"] == ""
    recs = records(live_env, "live")
    assert not recs["ci-a"].needs_call
    # ci-b: its verifier call went live; the blind confirm (gpt-6-luna) stayed cache-only.
    assert [(m.role, m.live) for m in recs["ci-b"].missed_calls] == [("confirm", False)]
    assert summary.meta.live_roles == ["verifier"] and not summary.meta.live_check
    assert 0 < summary.meta.total_cost_usd < 1
    # The live answers sit under the keys any later run reads: a pure replay hits them.
    monkeypatch.setenv("ANTHROPIC_API_KEY_BACKUP", "")
    sent.clear()
    await run_eval.run(config(live_env, "--offline", "--run-name", "again"))
    again = records(live_env, "again")
    assert sent == [] and [m.role for m in again["ci-b"].missed_calls] == ["confirm"]


async def test_live_check_records_the_calls_and_sends_nothing(
        live_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    await record_cache(live_env, monkeypatch)
    sent: Sent = []
    monkeypatch.setattr(completion, "_sync_completion", fake_provider(sent))
    summary = await run_eval.run(config(live_env, "--offline", "--live-roles", "verifier",
                                        "--live-check", "--run-name", "chk"))
    missed = records(live_env, "chk")["ci-b"]
    assert sent == [] and missed.needs_call and missed.verdict == "partially_supported"
    assert missed.missed_calls[0].live and missed.missed_calls[0].role == "verifier"
    assert summary.offline is not None and "live-chat:verifier" in summary.offline.calls_by_role
    assert summary.meta.live_check


def plan(max_cost: float = 1.0, check: bool = False) -> eval_live.LivePlan:
    return eval_live.LivePlan(models={"adjudicator": "claude-haiku-5-5"},
                              providers={"adjudicator": "anthropic"}, keep=[],
                              check=check, max_cost=max_cost)


async def test_stand_in_sends_only_live_role_calls_within_the_cap(
        monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[str] = []

    outcome = CompletionOutcome(content=ANSWER, usage=TokenUsage(), latency_ms=1)

    async def fake_complete(spec: object, messages: object, *a: object,
                            **k: object) -> CompletionOutcome:
        sent.append(str(k.get("role")))
        return outcome

    monkeypatch.setattr(completion, "complete", fake_complete)
    haiku, luna = spec_for("claude-haiku-5-5"), spec_for("gpt-6-luna")
    msgs = [{"role": "user", "content": "x" * 4000}]
    misses = eval_cache.item_misses()
    calls = eval_live.LiveCalls(plan())
    assert await calls.complete(haiku, msgs, None, role="adjudicator") is outcome
    for spec, role in ((haiku, "verifier"), (luna, "adjudicator")):  # cache-only
        with pytest.raises(LLMCallError):
            await calls.complete(spec, msgs, None, role=role)
    assert sent == ["adjudicator"] and [m.live for m in misses] == [False, False]
    with pytest.raises(LLMCallError, match="already needs a fallback"):
        await calls.complete(haiku, msgs, None, role="adjudicator")  # pair already missed
    misses = eval_cache.item_misses()
    tracker = CostTracker(max_cost=100)
    tracker.record_usage(haiku, TokenUsage(input_tokens=9_990), "t")  # $0.000999 spent
    capped = eval_live.LiveCalls(plan(max_cost=0.001))
    with pytest.raises(LLMCallError, match="max-cost"):
        await capped.complete(haiku, msgs, None, role="adjudicator", cost_tracker=tracker)
    with pytest.raises(LLMCallError, match="live-check"):
        await eval_live.LiveCalls(plan(check=True)).complete(haiku, msgs, None,
                                                             role="adjudicator")
    assert sent == ["adjudicator"] and [m.live for m in misses] == [True, True]


def test_live_plan_resolves_like_a_live_run_and_guards_keys(
        live_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", PRIMARY)
    monkeypatch.setenv("ANTHROPIC_API_KEY_BACKUP", BACKUP)
    monkeypatch.setenv("OPENAI_API_KEY", OPENAI)
    cfg = config(live_env, "--offline", "--live-roles", "adjudicator", "--live-keys",
                 "ANTHROPIC_API_KEY_BACKUP")
    got = eval_live.live_plan(cfg)
    assert got is not None and got.models == {"adjudicator": "claude-haiku-5-5"}
    assert got.keep == ["ANTHROPIC_API_KEY_BACKUP"] and eval_live.tracker_cap(cfg) > 1e9
    eval_cache.check_offline(cfg, True, got.keep)
    assert os.environ["ANTHROPIC_API_KEY"] == "" and os.environ["OPENAI_API_KEY"] == ""
    assert keys.get_key("anthropic") == BACKUP and not keys.has_key("openai")
    default = eval_live.live_plan(config(live_env, "--offline", "--live-roles", "adjudicator"))
    assert default is not None and default.keep == ["ANTHROPIC_API_KEY",
                                                    "ANTHROPIC_API_KEY_BACKUP"]
    with pytest.raises(SystemExit, match="not a key of"):
        eval_live.live_plan(config(live_env, "--offline", "--live-roles", "adjudicator",
                                   "--live-keys", "OPENAI_API_KEY"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    with pytest.raises(SystemExit, match="no anthropic key"):
        eval_live.live_plan(config(live_env, "--offline", "--live-roles", "adjudicator",
                                   "--live-keys", "ANTHROPIC_API_KEY"))


def test_cli_live_flags() -> None:
    cfg = parse_args(["--offline", "--live-roles", "adjudicator, verifier", "--live-keys",
                      "ANTHROPIC_API_KEY_BACKUP", "--live-check"])
    assert cfg.live_roles == ["adjudicator", "verifier"] and cfg.live_check
    assert cfg.live_keys == ["ANTHROPIC_API_KEY_BACKUP"]
    for argv in (["--live-roles", "adjudicator"], ["--offline", "--live-check"]):
        with pytest.raises(SystemExit):
            parse_args(argv)
    for role in ("embedding", "screen"):
        with pytest.raises(SystemExit, match="chat roles only"):
            parse_args(["--offline", "--live-roles", role])
