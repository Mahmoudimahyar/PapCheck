"""Stage-5 preflight with mocked LLM layers (V5.8 G1: only the verifier is a hard role)."""

from pathlib import Path

import pytest

from refcheck.llm.health import PreflightError
from refcheck.stages.verify_claims import verify_claims
from tests.unit.test_verifier import (  # noqa: F401 - fakes is a fixture
    Fakes,
    _pdf,
    _status,
    fakes,
)
from tests.unit.verify_fakes import make_claim, make_ref


async def test_preflight_failure_raises(fakes: Fakes, tmp_path: Path) -> None:  # noqa: F811
    """V5.8 G1: only a dead verifier (HARD_ROLES) fails stage 5; a dead judge does not."""
    fakes.preflight.side_effect = lambda roles, **_: {r: _status(r, r != "judge") for r in roles}
    assert await verify_claims([make_claim()], [make_ref(pdf_path=_pdf(tmp_path))])
    fakes.preflight.side_effect = lambda roles, **_: {r: _status(r, r != "verifier") for r in roles}
    with pytest.raises(PreflightError, match="verifier"):
        await verify_claims([make_claim()], [make_ref(pdf_path=_pdf(tmp_path))])


async def test_dead_screen_only_disables_screen(fakes: Fakes, tmp_path: Path) -> None:  # noqa: F811
    fakes.preflight.side_effect = lambda roles, **_: {r: _status(r, r != "screen") for r in roles}
    result = (await verify_claims([make_claim()], [make_ref(pdf_path=_pdf(tmp_path))]))[0]
    fakes.decide.assert_not_awaited()
    assert result.verdict == "supported" and result.decided_by == "verifier"
