"""Element adjudicator wiring: role defaults / overrides, cache keys, eval CLI and report."""

import os
import sys
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from refcheck.llm.cache import make_key
from refcheck.llm.model_registry import PROFILE_ROLE_DEFAULTS, REGISTRY, ROLE_DEFAULTS, ROLE_EFFORT
from refcheck.llm.roles import role_candidates
from refcheck.llm.schema import response_format_for
from refcheck.llm.structured import call_spec
from refcheck.models.adjudication import AdjudicateOutput
from tests.unit.llm_fakes import isolated_llm_env

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "eval"))

import eval_cli  # noqa: E402
import eval_report  # noqa: E402
import eval_roles  # noqa: E402
from eval_models import EvalConfig  # noqa: E402


@pytest.fixture
def llm_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    yield from isolated_llm_env(monkeypatch, tmp_path)


def test_adjudicator_role_defaults() -> None:
    assert ROLE_DEFAULTS["adjudicator"] == ["claude-haiku-5-5", "gpt-6-luna"]
    assert ROLE_EFFORT["adjudicator"] == "low"
    assert PROFILE_ROLE_DEFAULTS["anthropic_only"]["adjudicator"] == ["claude-haiku-5-5"]


def test_adjudicator_model_and_effort_overrides(llm_env: None,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    assert [s.id for s in role_candidates("adjudicator")] == ["claude-haiku-5-5", "gpt-6-luna"]
    monkeypatch.setenv("REFCHECK_ADJUDICATOR_MODEL", "gpt-6-luna")
    monkeypatch.setenv("REFCHECK_ADJUDICATOR_EFFORT", "none")
    [spec] = role_candidates("adjudicator")
    assert spec.id == "gpt-6-luna" and spec.reasoning_effort == "none"


async def _key_for(role: str) -> str:
    """The cache key call_spec reads for ``role`` (answered from a fake cache hit)."""
    seen: list[str] = []
    cached = AdjudicateOutput(elements=[], explanation="x").model_dump_json()

    def fake_get(key: str) -> str:
        seen.append(key)
        return cached

    with patch("refcheck.llm.structured.get_text", fake_get):
        await call_spec(REGISTRY["claude-haiku-5-5"], "user", "system", AdjudicateOutput,
                        role, 0, True, None, "t", None, None)  # type: ignore[arg-type]
    return seen[0]


async def test_cache_keys_scope_confirm_only() -> None:
    verifier, confirm = await _key_for("verifier"), await _key_for("confirm")
    adjudicator = await _key_for("adjudicator")
    assert confirm != verifier and adjudicator == verifier  # same prompt+model+schema
    spec = REGISTRY["claude-haiku-5-5"]
    legacy = make_key("chat", {
        "model": spec.litellm_id, "effort": spec.reasoning_effort, "user": "user",
        "system": "system", "format": response_format_for(spec, AdjudicateOutput),
        "out": "AdjudicateOutput"})
    assert verifier == legacy  # entries cached before the confirm rule stay valid


def test_eval_cli_accepts_the_adjudicator() -> None:
    cfg = eval_cli.parse_args(["--mode", "cascade", "--model", "adjudicator=gpt-6-luna",
                               "--effort", "adjudicator=low", "--adjudicate", "off"])
    assert cfg.models == {"adjudicator": "gpt-6-luna"}
    assert cfg.efforts == {"adjudicator": "low"} and cfg.adjudicate == "off"
    assert eval_cli.parse_args([]).adjudicate is None


def test_eval_overrides_and_roles(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REFCHECK_ADJUDICATOR_MODEL", raising=False)
    cfg = EvalConfig(mode="cascade", models={"adjudicator": "gpt-6-luna"}, adjudicate="on")
    eval_roles.apply_overrides(cfg)
    assert os.environ["REFCHECK_ADJUDICATOR_MODEL"] == "gpt-6-luna"
    assert "adjudicator" in eval_roles.run_roles(cfg, screen_on=False)
    monkeypatch.setenv("REFCHECK_ADJUDICATE", "off")
    assert "adjudicator" not in eval_roles.run_roles(cfg, screen_on=False)


def test_report_line() -> None:
    line = eval_report.adjudication_line({"cleared": 4, "partial": 2, "held": 3,
                                          "unchanged": 5, "error": 1})
    assert line == ("adjudicator: ran 15, cleared fully 4, partially 2 "
                    "(held 3, unchanged 5, errors 1)")
