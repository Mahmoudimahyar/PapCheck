"""Evidence re-check (taxonomy guard 1): per-element search of the whole paper + one re-run."""

import time
from unittest.mock import patch

from refcheck.llm import CostTracker
from refcheck.stages.verify_claims.calibration import ScreenThresholds
from refcheck.stages.verify_claims.cascade import run_cascade
from refcheck.stages.verify_claims.cascade_helpers import build_result
from refcheck.stages.verify_claims.layers import LayerResult
from refcheck.stages.verify_claims.recheck import (
    cleared_elements,
    evidence_recheck,
    recheck_pack,
    targeted_units,
    upgraded,
    wants_recheck,
)
from refcheck.stages.verify_claims.retriever import EvidencePack
from refcheck.stages.verify_claims.verifier_helpers import PairContext
from tests.unit.verify_fakes import layer, make_ctx

_ON = ScreenThresholds()
_ELEMENT = "body weight did not differ between the groups"


def with_elements(lay: LayerResult, *elements: str, ptype: str = "missing_element",
                  notes: tuple[str, ...] = ()) -> LayerResult:
    assert lay.output is not None
    out = lay.output.model_copy(update={"unsupported_elements": list(elements),
                                        "partial_type": ptype, "benign_notes": list(notes)})
    return lay.model_copy(update={"output": out})


def _ctx() -> PairContext:
    ctx = make_ctx()
    ctx.use_embeddings = False  # BM25 only: no embedding call in unit tests
    return ctx


def _first(verdict: str = "partially_supported") -> LayerResult:
    return with_elements(layer("verifier", verdict, severity="minor"), _ELEMENT)


def test_wants_recheck_only_for_flagged_full_text_with_elements() -> None:
    ctx, later = _ctx(), time.monotonic() + 100
    assert wants_recheck(ctx, _first(), None, later)
    assert wants_recheck(ctx, _first("not_supported"), None, later)
    assert not wants_recheck(ctx, with_elements(layer("verifier"), _ELEMENT), None, later)
    assert not wants_recheck(ctx, layer("verifier", "partially_supported"), None, later)
    assert not wants_recheck(ctx, _first(), None, time.monotonic() + 5)  # time budget
    spent = CostTracker(max_cost=0.0)
    assert not wants_recheck(ctx, _first(), spent, later)  # cost budget
    assert not wants_recheck(make_ctx(coverage="abstract_only"), _first(), None, later)
    expanded = _first().model_copy(update={"pack_kind": "expanded"})
    assert not wants_recheck(ctx, expanded, None, later)  # never a second re-run


async def test_targeted_pack_adds_new_windows_after_the_standard_ones() -> None:
    ctx = _ctx()
    picked = await targeted_units(ctx, [_ELEMENT], None)
    shown = {i for p in ctx.pack.passages for i in p.unit_idxs or [p.unit_idx]}
    assert picked and not shown & {idx for idx, _ in picked}
    pack = recheck_pack(ctx, picked, [_ELEMENT])
    assert pack.max_tokens == 8000 and pack.passages[0].id == "A"
    assert "Body weight did not differ" in pack.joined_text


def test_cleared_and_upgraded() -> None:
    second = with_elements(layer("verifier_recheck", "partially_supported"),
                           "Body weight did not differ between groups")
    assert cleared_elements([_ELEMENT, "restored limb function"], second) == [
        "restored limb function"]
    assert cleared_elements([_ELEMENT], layer("verifier_recheck")) == [_ELEMENT]
    assert upgraded(_first("not_supported"), _first()) and not upgraded(_first(), _first())


async def test_undecided_rerun_keeps_the_first_verdict() -> None:
    ctx, first = _ctx(), _first()

    async def rerun(pack: EvidencePack) -> LayerResult:
        return layer("verifier_recheck", "insufficient_evidence")

    res = await evidence_recheck(ctx, first, rerun, None, time.monotonic() + 100)
    assert res.ran and res.layer is first and not res.guard and ctx.recheck is not None


async def _route(script: dict[str, list[LayerResult]],
                 ctx: PairContext) -> tuple[list[str], object]:
    calls: list[str] = []

    async def fake_run_layer(role: str, pack: EvidencePack, claim: object, c: object,
                             template: str, **kwargs: object) -> LayerResult:
        calls.append(str(kwargs["layer"]))
        result = script[str(kwargs["layer"])].pop(0)
        return result.model_copy(update={"pack_kind": kwargs["pack_kind"]})

    with patch("refcheck.stages.verify_claims.cascade.run_layer", fake_run_layer):
        out = await run_cascade(ctx, None, _ON, deadline=time.monotonic() + 100)
    return calls, out


async def test_cascade_routes_on_the_recheck_and_records_the_guard() -> None:
    ctx = _ctx()
    calls, out = await _route({"verifier": [_first()],
                               "verifier_recheck": [layer("verifier_recheck")]}, ctx)
    assert calls == ["verifier", "verifier_recheck"]
    assert out.verdict == "supported" and out.guards == ["evidence_recheck"]  # type: ignore[attr-defined]
    assert out.layer_path == ["verifier", "verifier_recheck"]  # type: ignore[attr-defined]
    result = build_result(ctx, None, out, _ON, 1)  # type: ignore[arg-type]
    assert result.verdict == "supported" and result.guards_applied == ["evidence_recheck"]
    assert result.partial_type is None and "Evidence re-check:" in result.reasoning


async def test_negative_recheck_still_goes_to_the_cross_check() -> None:
    ctx = _ctx()
    second = with_elements(layer("verifier_recheck", "not_supported", role_quote="closest"),
                           _ELEMENT, ptype="tangential_source")
    calls, out = await _route({
        "verifier": [_first("not_supported")], "verifier_recheck": [second],
        "confirm": [layer("confirm", "not_supported", role_quote="closest",
                          provider="anthropic", model_id="claude-sonnet-5-5")]}, ctx)
    assert calls == ["verifier", "verifier_recheck", "confirm"]
    assert out.consensus_type == "confirmed" and out.guards == []  # type: ignore[attr-defined]
