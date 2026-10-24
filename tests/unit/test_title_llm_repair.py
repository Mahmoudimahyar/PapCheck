"""LLM title repair goes through the "utility" role and is cost-tracked."""

from unittest.mock import AsyncMock, patch

import pytest

from refcheck.models.reference import Reference
from refcheck.stages.parse_docx.title_llm_repair import (
    TitleRepairItem,
    TitleRepairResponse,
    batch_repair_titles,
    repair_reference_titles,
)

_CALL = "refcheck.stages.parse_docx.title_llm_repair.call_llm"


@pytest.mark.asyncio
async def test_uses_utility_role_and_tracker() -> None:
    tracker = object()
    mock = AsyncMock(return_value=TitleRepairResponse(repairs=[
        TitleRepairItem(index=0, title="Hydrogel scaffolds for cartilage repair"),
    ]))
    ref = Reference(id=1, title="Front", raw_text="Front. 2020;1:1")
    with patch(_CALL, mock):
        out = await batch_repair_titles([(0, ref)], cost_tracker=tracker)  # type: ignore[arg-type]
    assert out == {0: "Hydrogel scaffolds for cartilage repair"}
    kwargs = mock.call_args.kwargs
    assert kwargs["role"] == "utility"
    assert kwargs["task"] == "title_repair"
    assert kwargs["cost_tracker"] is tracker
    assert kwargs.get("model") is None  # never a hard-coded model


@pytest.mark.asyncio
async def test_repair_reference_titles_applies_llm_titles() -> None:
    refs = [
        Reference(id=1, title="Front", raw_text="Front"),
        Reference(id=2, title="A perfectly good title about bone healing"),
    ]
    mock = AsyncMock(return_value=TitleRepairResponse(repairs=[
        TitleRepairItem(index=0, title="Recovered title about tendon repair"),
    ]))
    with patch(_CALL, mock):
        out = await repair_reference_titles(refs)
    assert out[0].title == "Recovered title about tendon repair"
    assert out[0].repair_applied == "llm_title_repair"
    assert out[1] == refs[1]
    assert refs[0].title == "Front"  # input list untouched


@pytest.mark.asyncio
async def test_no_llm_call_when_titles_are_fine() -> None:
    mock = AsyncMock()
    refs = [Reference(id=1, title="A perfectly good title about bone healing")]
    with patch(_CALL, mock):
        assert await repair_reference_titles(refs) == refs
    mock.assert_not_called()
