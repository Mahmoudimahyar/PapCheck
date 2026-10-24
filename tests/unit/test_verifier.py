"""End-to-end verify_claims with mocked LLM layers (V5 cascade, no network)."""

from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import fitz
import pytest

from refcheck.llm import DecisionAnswer, DecisionResult, LLMCallError, RoleStatus
from refcheck.services.progress import ProgressSnapshot
from refcheck.stages.verify_claims import verify_claims
from refcheck.stages.verify_claims.credit import PANEL_PREFIX
from refcheck.stages.verify_claims.retrieval_embed import clear_embedding_cache
from tests.unit.credit_fakes import PANEL_A, PANEL_C, credit_claim, strip
from tests.unit.verify_fakes import (
    FULL_TEXT,
    RESULT_TEXT,
    judge_output,
    llm_result,
    make_claim,
    make_ref,
)

if TYPE_CHECKING:
    from refcheck.models.verification import JudgeOutput

_V = "refcheck.stages.verify_claims"
# Default model per role (the verifier and its cross-check are different families).
_ROLE_MODEL = {"verifier": ("claude-haiku-5-5", "anthropic"), "confirm": ("gpt-6-luna", "openai"),
               "judge": ("claude-sonnet-5-5", "anthropic")}


def _status(role: str, ok: bool = True) -> RoleStatus:
    return RoleStatus(role=role, available=ok, candidates=["m"],  # type: ignore[arg-type]
                      reason=None if ok else "billing: no credit")


def _pdf(tmp_path: Path) -> Path:
    path = tmp_path / "source.pdf"
    doc = fitz.open()
    for page_text in FULL_TEXT.split("\n\nResults\n\n"):
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(40, 40, 560, 800), page_text, fontsize=8)
    doc.save(str(path))
    doc.close()
    return path


class Fakes:
    def __init__(self) -> None:
        self.preflight = AsyncMock(side_effect=lambda roles, **_: {r: _status(r) for r in roles})
        probs = {"topic_match": 1.0, "finding_stated": 1.0, "evidence_sufficient": 1.0,
                 "finding_conflicts": 0.0, "claim_overreaches": 0.0,
                 "contains_instructions": 0.0}
        self.decide = AsyncMock(return_value=DecisionResult(
            model="gpt-6-luna-decisions", latency_ms=120, cost_usd=0.0004,
            answers={n: DecisionAnswer(name=n, type="predicate", probability=p)
                     for n, p in probs.items()}))
        self.outputs: dict[str, list[JudgeOutput]] = {}
        self.llm = AsyncMock(side_effect=self._llm)

    async def _llm(self, template: str, variables: object, output_model: object, **kwargs: object
                   ) -> object:
        role = str(kwargs["role"])
        queue = self.outputs.get(role) or [judge_output(
            "supported", [("P1", RESULT_TEXT, "supports")])]
        model_id, provider = _ROLE_MODEL.get(role, ("gpt-6-luna", "openai"))
        return llm_result(queue.pop(0) if len(queue) > 1 else queue[0], model_id, provider)

    def roles_called(self) -> list[str]:
        return [str(call.kwargs["role"]) for call in self.llm.await_args_list]


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> Iterator[Fakes]:
    for name in ("REFCHECK_SCREEN_ENABLED", "REFCHECK_PRIVACY_PROFILE",
                 "REFCHECK_SCREEN_T_ACCEPT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("REFCHECK_SCREEN_CALIBRATION", "does-not-exist.json")
    clear_embedding_cache()
    f = Fakes()
    with patch(f"{_V}.verifier.preflight", f.preflight), patch(f"{_V}.screen.decide", f.decide), \
            patch(f"{_V}.layers.call_llm_raw", f.llm), \
            patch(f"{_V}.retrieval_embed.embed_texts", AsyncMock(side_effect=RuntimeError("x"))):
        yield f


async def test_no_source_short_circuits_without_llm_calls(fakes: Fakes) -> None:
    ref = make_ref(doi="10.1/x")
    results = await verify_claims([make_claim()], [ref])
    assert len(results) == 1 and results[0].verdict == "cannot_verify"
    assert results[0].cannot_verify_reason == "no_pdf_paywalled"
    assert results[0].source_coverage == "no_source" and results[0].decided_by == "none"
    fakes.preflight.assert_not_awaited()
    fakes.llm.assert_not_awaited()
    fakes.decide.assert_not_awaited()


async def test_reference_mismatch_without_abstract(fakes: Fakes, tmp_path: Path) -> None:
    ref = make_ref(pdf_path=_pdf(tmp_path), identity_status="mismatch")
    result = (await verify_claims([make_claim()], [ref]))[0]
    assert result.cannot_verify_reason == "reference_mismatch"
    fakes.llm.assert_not_awaited()


async def test_mismatch_one_line_abstract_makes_no_call(fakes: Fakes, tmp_path: Path) -> None:
    """V5.6 E3: an editor's one-liner standing in for a wrong PDF never carries a verdict."""
    ref = make_ref(pdf_path=_pdf(tmp_path), identity_status="mismatch",
                   abstract_text="Drug X reduces inflammation in mice.", abstract_source="crossref")
    result = (await verify_claims([make_claim()], [ref]))[0]
    assert (result.verdict, result.cannot_verify_reason) == ("cannot_verify", "reference_mismatch")
    assert "too short" in result.reasoning
    fakes.llm.assert_not_awaited()


async def test_credit_lines_are_judged_on_their_own_legend_panel(fakes: Fakes,
                                                                tmp_path: Path) -> None:
    """V5.6 L1: CITED FOR of each repeated credit is the panel it closes."""
    claims = [credit_claim(1, base=0, nth=0), credit_claim(2, base=0, nth=1)]
    await verify_claims(claims, [make_ref(pdf_path=_pdf(tmp_path))])
    parts = {str(call.args[1]["cited_for"]) for call in fakes.llm.await_args_list}
    assert parts == {PANEL_PREFIX + strip(PANEL_A), PANEL_PREFIX + strip(PANEL_C)}
    assert claims[0].cited_for == "Adapted from Roe et al"  # the caller's claims untouched


async def test_full_text_pair_is_screen_cleared(fakes: Fakes, tmp_path: Path) -> None:
    snapshots: list[ProgressSnapshot] = []

    async def on_progress(snap: ProgressSnapshot) -> None:
        snapshots.append(snap)

    ref = make_ref(pdf_path=_pdf(tmp_path))
    result = (await verify_claims([make_claim()], [ref], progress_callback=on_progress))[0]
    assert result.verdict == "supported" and result.decided_by == "screen"
    assert result.layer_path == ["screen", "verifier"] and result.screen_p_support == 1.0
    assert result.source_coverage == "full_text" and result.cost_usd > 0
    assert len(snapshots) == 1 and snapshots[0].current == 1
    roles = fakes.preflight.await_args.args[0] if fakes.preflight.await_args else []
    assert list(roles) == ["verifier", "judge", "confirm", "screen"]
    assert fakes.llm.await_count == 1


async def test_abstract_only_negative_is_cross_checked_then_cannot_verify(fakes: Fakes) -> None:
    from tests.unit.verify_fakes import ABSTRACT

    fakes.outputs["verifier"] = [judge_output("not_supported", missing="No data.")]
    fakes.outputs["confirm"] = [judge_output("not_supported", missing="No data.")]
    ref = make_ref(abstract_text=ABSTRACT)
    result = (await verify_claims([make_claim()], [ref]))[0]
    assert result.verdict == "cannot_verify"
    assert result.cannot_verify_reason == "abstract_insufficient"
    assert result.layer_path == ["screen", "verifier", "confirm"]
    assert fakes.roles_called() == ["verifier", "confirm"]  # no judge on the negative path


async def test_disputed_not_supported_is_shown_as_partial_for_review(
    fakes: Fakes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M1: a not_supported verdict disputed by the cross-check is not shown as the harsher
    label; it becomes partially_supported (never "supported"), with both views recorded.
    The fake screen rates the finding stated, so the V5.8 #20 tie-break is switched off."""
    monkeypatch.setenv("REFCHECK_V57_DISABLE", "20")
    closest = [("P1", RESULT_TEXT, "closest")]
    fakes.outputs["verifier"] = [judge_output("not_supported", closest, missing="No data.")]
    fakes.outputs["confirm"] = [judge_output("supported", [("P1", RESULT_TEXT, "supports")])]
    result = (await verify_claims([make_claim()], [make_ref(pdf_path=_pdf(tmp_path))]))[0]
    assert result.verdict == "partially_supported" and result.decided_by == "verifier"
    assert result.consensus_type == "disputed" and result.needs_user_review
    assert "the verifier said not_supported" in result.reasoning
    assert "Verifier: No data." in result.reasoning and RESULT_TEXT in result.evidence_quotes
    assert result.confidence <= 0.70
    assert result.layer_path == ["screen", "verifier", "confirm"]
    assert fakes.roles_called() == ["verifier", "confirm"]


async def test_llm_failure_is_llm_error_with_coverage(fakes: Fakes, tmp_path: Path) -> None:
    fakes.llm.side_effect = LLMCallError("service down", "transient", "gpt-6-luna")
    ref = make_ref(pdf_path=_pdf(tmp_path))
    result = (await verify_claims([make_claim()], [ref]))[0]
    assert result.verdict == "cannot_verify" and result.cannot_verify_reason == "llm_error"
    assert result.source_coverage == "full_text"


async def test_missing_reference_is_skipped(fakes: Fakes) -> None:
    claim = make_claim().model_copy(update={"reference_ids": [99]})
    assert await verify_claims([claim], [make_ref()]) == []
