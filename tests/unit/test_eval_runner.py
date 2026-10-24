"""Unit tests for scripts/eval/eval_runner.py: every mode with fake layers (no network)."""

import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "eval"))

import eval_runner  # noqa: E402
from eval_data import build_document  # noqa: E402
from eval_models import EvalConfig, EvalItem  # noqa: E402

from refcheck.llm.cost_tracker import CostTracker  # noqa: E402
from refcheck.stages.verify_claims import cascade, recheck  # noqa: E402
from refcheck.stages.verify_claims.calibration import ScreenThresholds  # noqa: E402
from refcheck.stages.verify_claims.layers import LayerResult  # noqa: E402
from refcheck.stages.verify_claims.screen import ScreenResult  # noqa: E402
from refcheck.stages.verify_claims.verifier_helpers import PairContext  # noqa: E402
from tests.unit.verify_fakes import ABSTRACT, FULL_TEXT, layer, screen  # noqa: E402

ITEM = EvalItem.model_validate({
    "id": "ci-1", "claim": "Drug X reduces inflammation in treated mice [4].",
    "context": "Inflammation matters. Drug X reduces inflammation in treated mice [4].",
    "source_id": "PMC1", "source_title": "Drug X", "source_text": FULL_TEXT,
    "source_abstract": ABSTRACT, "gold_label": "supported", "gold_binary": "ok",
    "dataset": "citation_integrity", "fine_label": "ACCURATE"})


def install(monkeypatch: pytest.MonkeyPatch, script: Mapping[str, LayerResult],
            screen_result: ScreenResult | None = None) -> list[str]:
    calls: list[str] = []

    async def fake_layer(role: str, pack: object, claim: object, ctx: object, template: str,
                         **kw: object) -> LayerResult:
        name = str(kw["layer"])
        calls.append(f"{name}:{template}:{kw['pack_kind']}")
        return script[name]

    async def fake_screen(ctx: object, tracker: object = None) -> ScreenResult:
        calls.append("screen")
        return screen_result or screen(0.99)

    monkeypatch.setattr(eval_runner, "run_layer", fake_layer)
    monkeypatch.setattr(cascade, "run_layer", fake_layer)
    monkeypatch.setattr(eval_runner, "run_screen", fake_screen)
    return calls


async def evaluate(mode: str, **cfg: object) -> eval_runner.ItemRecord:
    config = EvalConfig.model_validate({"mode": mode, "use_embeddings": False, **cfg})
    doc = build_document(ITEM, 1, "auto")
    return await eval_runner.evaluate_item(ITEM, 1, 1, doc, config, ScreenThresholds(),
                                           CostTracker())


async def test_cascade_mode_records_a_screen_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install(monkeypatch, {"verifier": layer("verifier", "supported")})
    rec = await evaluate("cascade")
    assert calls == ["screen", "verifier:verify_claim:standard"]
    assert rec.verdict == "supported" and rec.decided_by == "screen"
    assert rec.clear_eligible is True and rec.gate_failures == []
    assert rec.layer_path == ["screen", "verifier"] and rec.error is None
    assert rec.coverage == "full_text" and rec.retrieval_version.endswith(":bm25")
    assert rec.cost_usd == pytest.approx(0.0005 + 0.001)


async def test_cascade_mode_cross_checks_a_negative_and_keeps_the_trace(
        monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install(monkeypatch, {
        "verifier": layer("verifier", "not_supported", role_quote="closest",
                          provider="anthropic", model_id="claude-haiku-5-5"),
        "confirm": layer("confirm", "supported", model_id="gpt-6-luna"),
    }, screen(0.2))
    rec = await evaluate("cascade")
    # V5.1: a negative verdict gets a blind cross-family check on the same pack, no judge
    assert calls == ["screen", "verifier:verify_claim:standard", "confirm:verify_claim:standard"]
    assert rec.layer_path == ["screen", "verifier", "confirm"]
    # V5.2 dispute policy: a disputed not_supported is shown as partially_supported (review)
    assert rec.decided_by == "verifier" and rec.verdict == "partially_supported"
    assert rec.needs_review and rec.consensus_type == "disputed"
    assert [lay.verdict for lay in rec.layers] == ["not_supported", "supported"]
    assert [lay.model_id for lay in rec.layers] == ["claude-haiku-5-5", "gpt-6-luna"]
    assert "below_threshold" not in rec.gate_failures and rec.clear_eligible is False


async def test_cascade_mode_cross_checks_an_unquoted_positive(
        monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install(monkeypatch, {
        "verifier": layer("verifier", "supported", supports=False),
        "confirm": layer("confirm", "not_supported", role_quote="closest", provider="openai",
                         model_id="gpt-6-luna"),
    }, screen(0.2))
    rec = await evaluate("cascade")
    assert calls == ["screen", "verifier:verify_claim:standard", "confirm:verify_claim:standard"]
    assert rec.layer_path == ["screen", "verifier", "confirm"]
    assert rec.decided_by == "verifier" and rec.verdict == "partially_supported"
    assert rec.needs_review
    assert rec.consensus_type == "disputed"


async def test_cascade_layer_failure_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, {"verifier": layer("verifier", None, error="transient: boom")})
    rec = await evaluate("cascade")
    assert rec.verdict == "cannot_verify" and rec.cannot_verify_reason == "llm_error"
    assert rec.error is not None and "boom" in rec.error


async def test_verifier_mode_reruns_on_the_expanded_pack(monkeypatch: pytest.MonkeyPatch,
                                                         ) -> None:
    calls = install(monkeypatch, {
        "verifier": layer("verifier", "insufficient_evidence", supports=False),
        "verifier_expanded": layer("verifier_expanded", "partially_supported"),
    })
    rec = await evaluate("verifier")
    assert calls == ["screen", "verifier:verify_claim:standard",
                     "verifier_expanded:verify_claim:expanded"]
    assert rec.verdict == "partially_supported"
    assert rec.layer_path == ["screen", "verifier", "verifier_expanded"]
    assert rec.cost_usd == pytest.approx(0.0005 + 0.002)
    assert rec.screen is not None and rec.screen.s == pytest.approx(0.99)


async def test_verifier_mode_without_screen(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install(monkeypatch, {"verifier": layer("verifier", "contradicted")})
    rec = await evaluate("verifier", with_screen=False)
    assert calls == ["verifier:verify_claim:standard"]
    assert rec.screen is None and rec.clear_eligible is None and rec.verdict == "contradicted"


@pytest.mark.parametrize(("mode", "expected_call"), [
    ("judge", "judge:judge_claim:expanded"),
    # V5.1: the confirm layer is a blind re-run of the verifier prompt on the same pack
    ("confirm", "confirm:verify_claim:standard"),
])
async def test_single_layer_modes_match_the_cascade(monkeypatch: pytest.MonkeyPatch,
                                                    mode: str, expected_call: str) -> None:
    calls = install(monkeypatch, {mode: layer(mode, "not_relevant", supports=False)})
    rec = await evaluate(mode)
    assert calls == [expected_call]
    assert rec.verdict == "not_relevant" and rec.screen is None
    assert rec.layer_path == [mode]


async def test_failed_single_layer_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, {"judge": layer("judge", None, error="budget: cost limit")})
    rec = await evaluate("judge")
    assert rec.verdict == "error" and rec.error == "budget: cost limit"


async def test_screen_mode_only_calls_the_screen(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install(monkeypatch, {})
    rec = await evaluate("screen")
    assert calls == ["screen"] and rec.verdict == "n/a" and rec.layers == []
    assert rec.clear_eligible is True and rec.error is None


async def test_unexpected_exception_becomes_an_error_record(
        monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("retrieval exploded")

    monkeypatch.setattr(eval_runner, "build_context", broken)
    rec = await evaluate("cascade")
    assert rec.error == "RuntimeError: retrieval exploded" and rec.verdict == "error"


def _typed(lay: LayerResult, ptype: str, *elements: str) -> LayerResult:
    assert lay.output is not None
    return lay.model_copy(update={"output": lay.output.model_copy(update={
        "partial_type": ptype, "unsupported_elements": list(elements)})})


async def test_verifier_mode_runs_the_evidence_recheck(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install(monkeypatch, {
        "verifier": _typed(layer("verifier", "partially_supported"), "missing_element",
                           "body weight did not differ between the groups"),
        "verifier_recheck": layer("verifier_recheck", "supported")})

    async def targeted(ctx: PairContext, elements: list[str], tracker: object) -> object:
        return [(ctx.doc.windows[-1].idx, 1.0)]  # the small test paper fits one pack

    monkeypatch.setattr(recheck, "targeted_units", targeted)
    rec = await evaluate("verifier", with_screen=False)
    assert calls == ["verifier:verify_claim:standard", "verifier_recheck:verify_claim:recheck"]
    assert rec.verdict == "supported" and rec.guards_applied == ["evidence_recheck"]
    assert rec.partial_type == "" and rec.layer_path == ["verifier", "verifier_recheck"]


async def test_cascade_records_the_product_partial_fields(monkeypatch: pytest.MonkeyPatch,
                                                          ) -> None:
    install(monkeypatch, {
        "verifier": _typed(layer("verifier", "not_supported", role_quote="closest"),
                           "tangential_source"),
        "confirm": layer("confirm", "not_supported", role_quote="closest",
                         provider="anthropic", model_id="claude-sonnet-5-5")}, screen(0.2))
    rec = await evaluate("cascade")
    assert rec.verdict == "not_supported" and rec.consensus_type == "confirmed"
    assert (rec.partial_type, rec.partial_severity) == ("tangential_source", "major")
    assert rec.guards_applied == [] and rec.unsupported_elements == []
