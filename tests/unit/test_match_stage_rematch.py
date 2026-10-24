"""Stage 3 runner: the re-match pass runs after the first pass, before persisting."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from refcheck.models.matching import MatchResult
from refcheck.models.pipeline import PipelineEvent, PipelineState
from refcheck.models.reference import Reference
from refcheck.services import stage_runners
from tests.unit.rematch_fakes import article, ref


async def test_run_match_links_a_reference_the_first_pass_missed(tmp_path: Path) -> None:
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    article(pdf_dir / "SM-1.pdf", doi_line="https://doi.org/10.5555/SYNTH\n.01234-56",
            meta_title="SM-AMAC000000 1..16")
    events: list[PipelineEvent] = []
    persist = MagicMock()

    async def _emit(session_id: str, event: PipelineEvent) -> None:
        events.append(event)

    def _first_pass(references: list[Reference], directory: Path) -> list[MatchResult]:
        return []

    with (
        patch.object(stage_runners, "match_pdfs", _first_pass),
        patch.object(stage_runners, "pdf_identity_status", lambda r, p: "verified"),
        patch.object(stage_runners, "emit_event", _emit),
        patch.object(stage_runners, "persist_references", persist),
        patch.object(stage_runners, "update_stage", MagicMock()),
    ):
        state = await stage_runners.run_match(
            "s1", tmp_path, PipelineState(session_id="s1", references=[ref(11)]))

    linked = state.references[0]
    assert linked.pdf_path is not None and linked.pdf_path.name == "SM-1.pdf"
    assert linked.pdf_source == "user_upload"
    assert [r.reference_id for r in state.match_results] == [11]
    assert persist.call_args.args[1][0].pdf_path == linked.pdf_path
    assert events[-1].message == "1 PDFs matched; 1 re-matched by DOI/title"
