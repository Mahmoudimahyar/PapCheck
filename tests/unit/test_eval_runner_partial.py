"""Eval single-layer mode maps partial fields with the same inputs as production."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "eval"))

from refcheck.stages.verify_claims import recheck  # noqa: E402
from refcheck.stages.verify_claims.layers import LayerResult  # noqa: E402
from refcheck.stages.verify_claims.verifier_helpers import PairContext  # noqa: E402
from tests.unit.test_eval_runner import evaluate, install  # noqa: E402
from tests.unit.verify_fakes import layer  # noqa: E402

_FOUND = "body weight did not differ between the groups"
_ABSENT = "restored limb function"


def _partial(name: str, *elements: str) -> LayerResult:
    lay = layer(name, "partially_supported", severity="minor")
    assert lay.output is not None
    return lay.model_copy(update={"output": lay.output.model_copy(update={
        "partial_type": "missing_element", "unsupported_elements": list(elements)})})


async def test_verifier_mode_partial_keeps_the_recheck_clearing(
        monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, {"verifier": _partial("verifier", _FOUND, _ABSENT),
                          "verifier_recheck": _partial("verifier_recheck", _ABSENT)})

    async def targeted(ctx: PairContext, elements: list[str], tracker: object) -> object:
        return [(ctx.doc.windows[-1].idx, 1.0)]

    monkeypatch.setattr(recheck, "targeted_units", targeted)
    rec = await evaluate("verifier", with_screen=False)
    assert rec.verdict == "partially_supported" and rec.partial_type == "missing_element"
    assert rec.guards_applied == ["evidence_recheck"] and rec.unsupported_elements == [_ABSENT]
