"""V5.4 partial sub-types end to end (offline): routing and guards (partial_e2e_fakes).

(a) the targeted re-check finds an element the standard pack left out -> supported +
    evidence_recheck; (b) the rest of the sentence is a co-cited reference's share ->
    supported + cocited_share and the citation-placement note. Synthetic data only.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from refcheck.llm.templates import render_template
from refcheck.models.partial_types import GUARD_LABELS
from refcheck.stages.verify_claims.taxonomy_prompt import system_variables
from tests.unit.partial_e2e_fakes import (
    SAFETY,
    TITLES,
    RunResult,
    ScriptedFakes,
    run_all,
    scripted,
)


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> Iterator[ScriptedFakes]:
    with scripted(monkeypatch) as f:
        yield f


@pytest.fixture
async def run(fakes: ScriptedFakes, tmp_path: Path) -> RunResult:
    return await run_all(fakes, tmp_path)


async def test_recheck_finds_the_missing_element(run: RunResult) -> None:
    fakes, _, results = run
    calls = fakes.calls(1)
    assert [c["pack_kind"] for c in calls] == ["standard", "recheck"]
    assert SAFETY[:30] not in str(calls[0]["passages"])  # the standard pack missed it
    assert SAFETY[:30] in str(calls[1]["passages"])
    a = results[1]
    assert a.verdict == "supported" and a.guards_applied == ["evidence_recheck"]
    assert a.layer_path == ["verifier", "verifier_recheck"] and a.partial_type is None


async def test_cocited_share_clears_and_reaches_the_prompt(
    run: RunResult,
) -> None:
    fakes, _, results = run
    call = fakes.calls(2)[0]
    assert call["co_cited"] == [{"number": 3, "title": TITLES[3],
                                 "abstract": "Hydrogel R lowered fibrosis in pig livers."}]
    user = render_template("verify_claim", {k: v for k, v in call.items()
                                            if k not in ("role", "system")})
    assert "CO-CITED REFERENCES" in user and TITLES[3] in user
    assert "cocited_share" in render_template("verify_claim", call["system"])  # type: ignore[arg-type]
    b = results[2]
    assert b.verdict == "supported" and b.guards_applied == ["cocited_share"]
    assert b.author_action == GUARD_LABELS["cocited_share"][1] and b.partial_type is None


def test_rendered_prompt_includes_the_taxonomy() -> None:
    system = render_template("verify_claim", system_variables())
    assert "scope_overgeneralized" in system and "cocited_share" in system
