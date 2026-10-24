"""Pipeline runner: a failed verification stage errors the session and stops."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from refcheck.models.pipeline import PipelineState
from refcheck.services.verify_outcome import VerificationStageError


@pytest.mark.asyncio
async def test_pipeline_marks_session_error_and_stops() -> None:
    from refcheck.services import pipeline_runner as pr

    async def _same(*args: object, **kwargs: object) -> PipelineState:
        state = args[-1] if isinstance(args[-1], PipelineState) else args[-2]
        assert isinstance(state, PipelineState)
        return state

    async def _fail(*args: object, **kwargs: object) -> PipelineState:
        raise VerificationStageError("Verification failed: RuntimeError: no judge")

    async def _noop(*args: object, **kwargs: object) -> None:
        return None

    status = MagicMock()
    later = MagicMock()
    parse_args: list[object] = []

    async def _parse(*args: object, **kwargs: object) -> PipelineState:
        parse_args.extend(args)
        return await _same(*args)

    async def _later(*args: object, **kwargs: object) -> PipelineState:
        later()
        return await _same(*args)

    with (
        patch.object(pr, "run_parse", _parse),
        patch.object(pr, "run_detect_citations", _same),
        patch.object(pr, "run_match", _same),
        patch.object(pr, "run_resolve", _same),
        patch.object(pr, "run_verify", _fail),
        patch.object(pr, "run_missing_citations", _later),
        patch.object(pr, "run_report", _later),
        patch.object(pr, "emit_event", _noop),
        patch.object(pr, "close_event_stream", _noop),
        patch.object(pr, "_clear_stale_events", MagicMock()),
        patch.object(pr, "_update_status", status),
    ):
        await pr.run_pipeline("s1", Path("unused"))

    later.assert_not_called()
    assert status.call_args_list[0].kwargs == {"clear_error": True}
    final = status.call_args_list[-1]
    assert final.args[1] == "error"
    assert "no judge" in final.kwargs["error_message"]
    assert any(type(a).__name__ == "CostTracker" for a in parse_args)


@pytest.mark.asyncio
async def test_degraded_roles_are_saved_for_the_report(tmp_path: Path) -> None:
    from refcheck.llm import degradation
    from refcheck.llm.cost_tracker import CostTracker
    from refcheck.services import pipeline_runner as pr

    async def _verify(session_id: str, state: PipelineState,
                      tracker: CostTracker) -> PipelineState:
        tracker.note_degraded(degradation.build(
            "confirm", "fallback", kind="billing", provider="openai",
            fallback_model="claude-sonnet-5-5"))
        raise VerificationStageError("stopped after recording")

    with patch.object(pr, "run_verify", _verify), pytest.raises(VerificationStageError):
        await pr._verify("s1", tmp_path, PipelineState(session_id="s1"), CostTracker())
    saved = degradation.load(tmp_path / pr.DEGRADATIONS_FILE)
    assert saved["confirm"].cause == "billing" and saved["confirm"].persistent
