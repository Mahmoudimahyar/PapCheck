"""Run the real cascade + build_result with scripted layers and a scripted adjudicator."""

import time
from collections.abc import Awaitable, Callable
from unittest.mock import patch

from refcheck.llm import CostTracker
from refcheck.models.verification import VerificationResult
from refcheck.stages.verify_claims.calibration import ScreenThresholds
from refcheck.stages.verify_claims.cascade import CascadeOutcome, run_cascade
from refcheck.stages.verify_claims.cascade_helpers import build_result
from refcheck.stages.verify_claims.layers import LayerResult
from refcheck.stages.verify_claims.lineage import lineage_action
from refcheck.stages.verify_claims.recheck import RecheckOutcome
from refcheck.stages.verify_claims.retriever import EvidencePack
from refcheck.stages.verify_claims.verifier_helpers import PairContext
from tests.unit.adjudicate_fakes import Responder, fake_call
from tests.unit.verify_fakes import layer

_ON = ScreenThresholds()
RerunFn = Callable[[EvidencePack], Awaitable[LayerResult]]


def haiku(verdict: str, supports: bool = True, role_quote: str = "supports") -> LayerResult:
    return layer("verifier", verdict, supports=supports, role_quote=role_quote,
                 provider="anthropic", model_id="claude-haiku-5-5")


def luna(verdict: str, supports: bool = True) -> LayerResult:
    return layer("confirm", verdict, supports=supports, provider="openai",
                 model_id="gpt-6-luna")


def recheck_layer(verdict: str) -> LayerResult:
    return layer("verifier_recheck", verdict, provider="anthropic", model_id="claude-haiku-5-5")


async def route(ctx: PairContext, script: dict[str, list[LayerResult]],
                respond: Responder, calls: list[dict[str, object]] | None = None,
                recheck_cleared: list[str] | None = None, tracker: CostTracker | None = None,
                ) -> tuple[CascadeOutcome, VerificationResult]:
    """Cascade with scripted layers. A "verifier_recheck" entry is used as the evidence
    re-check's re-run (guard earned, ``recheck_cleared`` no longer reported)."""
    async def fake_run_layer(role: str, pack: object, claim: object, c: object,
                             template: str, **kwargs: object) -> LayerResult:
        return script[str(kwargs["layer"])].pop(0)

    async def fake_recheck(c: PairContext, l2: LayerResult, rerun: RerunFn,
                           tracker: object, deadline: float) -> RecheckOutcome:
        if not script.get("verifier_recheck"):
            return RecheckOutcome(layer=l2)
        ctx.recheck = ctx.pack
        second = await rerun(ctx.pack)
        return RecheckOutcome(layer=second, ran=True, cleared=list(recheck_cleared or []),
                              guard=True)

    with (patch("refcheck.stages.verify_claims.cascade.run_layer", fake_run_layer),
          patch("refcheck.stages.verify_claims.cascade.evidence_recheck", fake_recheck),
          fake_call(respond, calls)):
        out = await run_cascade(ctx, None, _ON, deadline=time.monotonic() + 100,
                                cost_tracker=tracker)
    return out, build_result(ctx, None, out, _ON, 10)


def assert_coherent(result: VerificationResult) -> None:
    """Fields every path must keep consistent (UI/report contract)."""
    assert len(result.layer_path) == len(result.model_reasoning) == len(result.votes)
    if result.verdict == "supported":
        assert result.partial_type is None and result.partial_severity is None
        assert not result.unsupported_elements
    elif result.verdict == "partially_supported":
        assert result.partial_type and result.partial_severity in ("minor", "major")
        assert result.unsupported_elements
        first = result.unsupported_elements[0]
        # a lineage element gets its own action naming both years (lineage.lineage_action)
        assert (first.strip(".") in result.author_action
                or lineage_action(first) == result.author_action)
    for guard in result.guards_applied:
        assert guard in ("evidence_recheck", "cocited_share", "author_framing_or_example",
                         "overliteral_wording")
    if "adjudicate" in result.layer_path:  # last, or followed by the co-cited union check
        assert result.layer_path.count("adjudicate") == 1
        tail = [p for p in result.layer_path[result.layer_path.index("adjudicate"):]
                if p != "post_rules"]  # the deterministic rules run last (outcome_rules)
        assert tail in (["adjudicate"], ["adjudicate", "adjudicate_cocited"])
    if "post_rules" in result.layer_path:
        assert result.layer_path[-1] == "post_rules"
