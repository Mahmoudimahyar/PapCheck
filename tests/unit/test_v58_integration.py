"""V5.8 integration: the G1 degraded-mode hand-offs (report, eval preflight, dispute
wording) and the Unpaywall contact rule. Fakes only, no network, no keys."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import docx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "eval"))

from eval_cli import parse_args  # noqa: E402
from eval_roles import check_roles  # noqa: E402

from refcheck.llm import degradation  # noqa: E402
from refcheck.llm.cost_tracker import CostTracker  # noqa: E402
from refcheck.llm.health import PreflightError  # noqa: E402
from refcheck.llm.roles import RoleStatus  # noqa: E402
from refcheck.models.claim import Claim  # noqa: E402
from refcheck.models.pipeline import PipelineState  # noqa: E402
from refcheck.models.reference import ParsedManuscript, Reference  # noqa: E402
from refcheck.models.verification import VerificationResult  # noqa: E402
from refcheck.stages.generate_report import generate_report  # noqa: E402
from refcheck.stages.resolve_gaps.unpaywall_client import find_open_access_pdf  # noqa: E402
from refcheck.stages.verify_claims.calibration import ScreenThresholds  # noqa: E402
from refcheck.stages.verify_claims.dispute import dispute_note, who  # noqa: E402
from refcheck.stages.verify_claims.layers import LayerResult  # noqa: E402


def _state() -> PipelineState:
    result = VerificationResult(claim_id=1, reference_id=1, verdict="supported",
                                confidence=0.9, reasoning="Stated.")
    return PipelineState(session_id="s", manuscript=ParsedManuscript(filename="m.docx"),
                         references=[Reference(id=1, title="Paper", source_status="found")],
                         claims=[Claim(id=1, extracted_claim="A claim", reference_ids=[1])],
                         verification_results=[result])


def _text(path: Path) -> str:
    return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)


def test_report_names_degraded_roles(tmp_path: Path) -> None:
    item = degradation.build("confirm", "fallback", kind="billing", provider="openai",
                             reason="insufficient_quota", fallback_model="claude-sonnet-5-5")
    degradation.save(tmp_path / degradation.RUN_FILE, {"confirm": item})
    lines = [degradation.describe(i)
             for i in degradation.load(tmp_path / degradation.RUN_FILE).values()]
    text = _text(generate_report(_state(), tmp_path / "r.docx", lines))
    assert "Degraded mode" in text
    assert "claude-sonnet-5-5" in text and "Add credits to the OpenAI account" in text


def test_report_without_degradation_has_no_note(tmp_path: Path) -> None:
    assert "Degraded mode" not in _text(generate_report(_state(), tmp_path / "r.docx"))


def _layer(role: str, model: str, verdict: str) -> LayerResult:
    return LayerResult(layer=role, role=role, model_id=model)  # type: ignore[arg-type]


def test_dispute_wording_names_a_same_family_cross_check() -> None:
    l2 = _layer("verifier", "claude-haiku-5-5", "not_supported")
    assert "another family" in who(l2, _layer("confirm", "gpt-6-luna", "supported"))
    same = _layer("confirm", "claude-sonnet-5-5", "supported")
    assert "same family" in who(l2, same)
    assert "same family" in dispute_note(l2, same, "partially_supported")
    # no model ids (code-built layers): the normal wording
    assert "another family" in who(LayerResult(layer="verifier", role="verifier"),
                                   LayerResult(layer="confirm", role="confirm"))


def _statuses(dead: str) -> dict[str, RoleStatus]:
    def one(role: str) -> RoleStatus:
        ok = role != dead
        return RoleStatus(role=role, model_id="m" if ok else None,  # type: ignore[arg-type]
                          available=ok, reason=None if ok else "billing: no credits",
                          candidates=["m"])
    return {r: one(r) for r in ("verifier", "judge", "confirm", "adjudicator", "screen")}


@pytest.mark.parametrize("dead", ["confirm", "judge", "screen", "adjudicator"])
async def test_eval_cascade_preflight_survives_a_soft_role(dead: str) -> None:
    cfg = parse_args(["--dataset", "smoke", "--mode", "cascade"])
    fake = AsyncMock(side_effect=lambda roles, **_: {r: _statuses(dead)[r] for r in roles})
    with patch("eval_roles.preflight", fake):
        thresholds, _, _ = await check_roles(cfg, ScreenThresholds(), CostTracker())
    assert thresholds.enabled == (dead != "screen")


async def test_eval_preflight_still_needs_the_verifier_and_the_measured_role() -> None:
    for mode, dead in (("cascade", "verifier"), ("confirm", "confirm")):
        cfg = parse_args(["--dataset", "smoke", "--mode", mode])
        fake = AsyncMock(side_effect=lambda roles, d=dead, **_: {r: _statuses(d)[r]
                                                                 for r in roles})
        with patch("eval_roles.preflight", fake), pytest.raises(PreflightError, match=dead):
            await check_roles(cfg, ScreenThresholds(), CostTracker())


async def test_unpaywall_needs_a_real_contact_email(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNPAYWALL_EMAIL", "")
    with patch("httpx.AsyncClient") as client:
        assert await find_open_access_pdf("10.1/x") is None
    client.assert_not_called()  # nothing is sent without an address


@pytest.mark.parametrize(("mode", "recorded"), [("miss", 1), ("bm25", 0)])
async def test_offline_embedding_miss_modes(mode: str, recorded: int) -> None:
    """--embedding-miss bm25: an uncached embedding fails softly and is not a needs_call."""
    import eval_cache

    from refcheck.llm import embeddings
    from refcheck.llm.errors import LLMCallError
    from refcheck.llm.model_lookup import spec_for

    assert parse_args(["--dataset", "smoke", "--offline", "--embedding-miss", "bm25"]
                      ).embedding_miss == "bm25"
    assert parse_args(["--dataset", "smoke", "--embedding-miss", "bm25"]).embedding_miss == "miss"
    with eval_cache.offline_scope(True, embedding_miss=mode):
        misses = eval_cache.item_misses()
        with pytest.raises(LLMCallError):
            await embeddings._embed_batch(spec_for("text-embedding-3-small", "embedding"),
                                          ["text"], None, "retrieval")
    assert len(misses) == recorded
