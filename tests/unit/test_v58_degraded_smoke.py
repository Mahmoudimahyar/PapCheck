"""V5.8 G1 smoke: a whole stage-5 run with the OpenAI account out of credits.

Only the provider boundary is faked (litellm chat / embedding / decisions): every
OpenAI call fails with insufficient_quota, Anthropic answers. The real preflight,
role resolution, degraded fallback, retrieval and cascade run. The stage must not
abort: the screen is skipped, retrieval is BM25-only, and a negative verdict is
cross-checked by the same-family fallback (claude-sonnet-5-5) and queued for review.
"""

import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import litellm
import pytest

from refcheck.llm.cost_tracker import CostTracker
from refcheck.stages.verify_claims import verify_claims
from refcheck.stages.verify_claims.retrieval_embed import clear_embedding_cache
from tests.unit.llm_fakes import chat_response, isolated_llm_env
from tests.unit.test_verifier import _pdf
from tests.unit.verify_fakes import make_claim, make_ref

_NEGATIVE = {"verdict": "not_supported", "severity": "major", "problem_type": "not_in_source",
             "confidence": 0.8, "quotes": [], "explanation": "Not stated [P1].",
             "missing": "the claimed effect", "partial_type": "none",
             "unsupported_elements": [], "benign_notes": []}


def _no_credits(model: str) -> Exception:
    return litellm.exceptions.RateLimitError(
        "Error code: 429 - You exceeded your current quota (insufficient_quota)",
        "openai", model)


class Provider:
    """Fake provider boundary: OpenAI has no credits; Anthropic answers."""

    def __init__(self) -> None:
        self.chat_models: list[str] = []

    def chat(self, kwargs: dict[str, object]) -> object:
        model = str(kwargs["model"])
        self.chat_models.append(model)
        if model.startswith("openai/"):
            raise _no_credits(model)
        fmt = json.dumps(kwargs.get("response_format") or {})
        reply = {"ok": True} if "PreflightReply" in fmt else _NEGATIVE
        return chat_response(json.dumps(reply))


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    clear_embedding_cache()
    yield from isolated_llm_env(monkeypatch, tmp_path)
    clear_embedding_cache()


async def test_stage5_runs_degraded_without_openai(tmp_path: Path) -> None:
    provider = Provider()
    tracker = CostTracker(max_cost=5.0)

    def fail(*args: object, **kwargs: object) -> object:
        raise _no_credits(str(kwargs.get("model", "openai")))

    with patch("refcheck.llm.completion._sync_completion", side_effect=provider.chat), \
            patch.object(litellm, "embedding", side_effect=fail, create=True), \
            patch.object(litellm, "decisions", side_effect=fail, create=True):
        results = await verify_claims([make_claim()], [make_ref(pdf_path=_pdf(tmp_path))],
                                      cost_tracker=tracker)
    assert len(results) == 1
    result = results[0]
    assert result.cannot_verify_reason != "llm_error"
    assert "confirm" in result.layer_path and result.needs_user_review
    assert any("claude-sonnet" in m for m in provider.chat_models)  # same-family confirm
    degraded = tracker.summary().degraded
    assert {"confirm", "screen", "embedding"} <= set(degraded)  # embedding: BM25-only
    assert "Add credits to the OpenAI account" in degraded["confirm"]


async def test_eval_preflight_runs_degraded_without_openai() -> None:
    """run_eval's cascade preflight (eval_roles.check_roles) no longer aborts on confirm."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "eval"))
    from eval_cli import parse_args
    from eval_roles import check_roles

    from refcheck.stages.verify_claims.calibration import ScreenThresholds

    provider = Provider()

    def fail(*args: object, **kwargs: object) -> object:
        raise _no_credits("gpt-6-luna-decisions")

    cfg = parse_args(["--dataset", "smoke", "--mode", "cascade"])
    tracker = CostTracker()
    with patch("refcheck.llm.completion._sync_completion", side_effect=provider.chat), \
            patch.object(litellm, "decisions", side_effect=fail, create=True):
        thresholds, models, _ = await check_roles(cfg, ScreenThresholds(), tracker)
    assert thresholds.enabled is False  # screen skipped
    assert models["confirm"] == "claude-sonnet-5-5" and models["verifier"] == "claude-haiku-5-5"
    assert {"confirm", "screen"} <= set(tracker.summary().degraded)
