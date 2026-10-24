"""run_eval.py --dry-run: the whole eval path with canned answers and no API call."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "eval"))

import eval_dry_run  # noqa: E402
import run_eval  # noqa: E402

from refcheck.models.verification import JudgeOutput  # noqa: E402
from refcheck.stages.verify_claims import layers  # noqa: E402
from refcheck.stages.verify_claims.taxonomy_prompt import system_variables  # noqa: E402
from tests.unit.verify_fakes import ABSTRACT, FULL_TEXT, make_ctx  # noqa: E402


def test_parse_cli_forces_an_offline_configuration() -> None:
    cfg = eval_dry_run.parse_cli(["--dataset", "smoke", "--dry-run"], None)
    assert cfg.dry_run and not cfg.use_embeddings and not cfg.with_screen
    assert not cfg.reuse_cache
    assert not eval_dry_run.parse_cli(["--dataset", "smoke"], None).dry_run


async def test_fake_call_renders_both_prompts_and_answers() -> None:
    ctx = make_ctx()
    first = layers.layer_variables(ctx.claim, ctx, ctx.pack, "standard")
    result = await eval_dry_run.fake_call_llm_raw(
        "verify_claim", first, JudgeOutput, system_template="verify_claim",
        system_variables=system_variables())
    out = result.parsed
    assert out.verdict == "partially_supported" and out.unsupported_elements
    assert out.quotes and out.quotes[0].passage_id == "A" and result.cost_usd == 0.0
    again = layers.layer_variables(ctx.claim, ctx, ctx.pack, "recheck")
    assert eval_dry_run.canned_output(again).verdict == "supported"


async def test_scope_patches_the_layers_and_blocks_paid_apis() -> None:
    original = layers.call_llm_raw
    with eval_dry_run.dry_run_scope(True):
        assert layers.call_llm_raw is eval_dry_run.fake_call_llm_raw
        with pytest.raises(RuntimeError, match="dry run"):
            await eval_dry_run.no_api_call()
    assert layers.call_llm_raw is original
    with eval_dry_run.dry_run_scope(False):
        assert layers.call_llm_raw is original


async def test_dry_run_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [{"id": f"syn-{i}", "claim": "Drug X reduced IL-6 levels by 40% in mice.",
             "source_id": f"S{i}", "source_title": "Drug X", "source_text": FULL_TEXT,
             "source_abstract": ABSTRACT, "gold_label": "supported", "gold_binary": "ok",
             "dataset": "synthetic", "synthetic": True} for i in range(2)]
    data = tmp_path / "syn.jsonl"
    data.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    monkeypatch.setattr(run_eval, "load_dotenv", lambda *a, **k: None)
    cfg = eval_dry_run.parse_cli(["--dataset", str(data), "--dry-run", "--run-name", "t",
                                  "--results-dir", str(tmp_path)], None)
    result = await run_eval.run(cfg)
    assert result.meta.dry_run and result.meta.total_cost_usd == 0.0
    records = (tmp_path / "t" / "items.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(records) == 2 and all('"error":null' in r for r in records)


async def test_dry_run_runs_the_element_adjudicator(tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [{"id": "syn-abs", "claim": "Drug X reduced inflammation markers in mice.",
             "source_id": "S0", "source_title": "Drug X", "source_text": ABSTRACT,
             "source_type": "abstract", "gold_label": "supported", "gold_binary": "ok",
             "dataset": "synthetic", "synthetic": True}]
    data = tmp_path / "abs.jsonl"
    data.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    monkeypatch.setattr(run_eval, "load_dotenv", lambda *a, **k: None)
    cfg = eval_dry_run.parse_cli(["--dataset", str(data), "--dry-run", "--run-name", "a",
                                  "--results-dir", str(tmp_path), "--adjudicate", "on"], None)
    result = await run_eval.run(cfg)
    assert result.meta.adjudicate and result.headline.adjudication == {}  # synthetic only
    assert result.synthetic is not None and result.synthetic.adjudication == {"cleared": 1}
    record = json.loads((tmp_path / "a" / "items.jsonl").read_text(encoding="utf-8"))
    assert record["adjudication"] == "cleared" and record["verdict"] == "supported"
    assert record["adjudicated_elements"] == {"stated": 1}
    last = record["layers"][-1]
    assert (last["layer"], last["role"], last["model_id"], last["verdict"]) == (
        "adjudicate", "adjudicator", "dry-run", "supported")
