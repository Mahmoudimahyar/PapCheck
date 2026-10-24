"""Stage 4 runner: summary message and shared-library hygiene."""

from unittest.mock import MagicMock, patch

import pytest

from refcheck.models.pipeline import PipelineEvent, PipelineState
from refcheck.models.reference import Reference
from refcheck.services import stage_runners
from refcheck.services.stage_runners import resolve_summary


def _refs() -> list[Reference]:
    return [
        Reference(id=1, source_status="found", abstract_text="x" * 60),
        Reference(id=2, source_status="found", identity_status="mismatch"),
        Reference(id=3, source_status="not_found", retraction_status="retracted"),
    ]


def test_resolve_summary() -> None:
    assert resolve_summary(_refs()) == (
        "2 found, 1 not found, 1 with abstract, 1 PDF identity mismatch, 1 retracted"
    )
    assert resolve_summary([]) == "0 found"


@pytest.mark.asyncio
async def test_run_resolve_never_adds_mismatched_pdf_to_library() -> None:
    events: list[PipelineEvent] = []
    populate = MagicMock(return_value=0)

    async def _emit(session_id: str, event: PipelineEvent) -> None:
        events.append(event)

    async def _resolve(refs: list[Reference]) -> list[Reference]:
        return _refs()

    with (
        patch("refcheck.services.library.enrich_from_library", side_effect=lambda r: r),
        patch("refcheck.services.library.populate_library", populate),
        patch.object(stage_runners, "resolve_gaps", _resolve),
        patch.object(stage_runners, "emit_event", _emit),
        patch.object(stage_runners, "persist_references", MagicMock()),
        patch.object(stage_runners, "update_stage", MagicMock()),
    ):
        state = await stage_runners.run_resolve("s1", PipelineState(session_id="s1"))

    added = populate.call_args.args[0]
    assert [r.id for r in added] == [1, 3]
    assert len(state.references) == 3
    assert events[-1].status == "complete"
    assert "1 PDF identity mismatch" in events[-1].message
