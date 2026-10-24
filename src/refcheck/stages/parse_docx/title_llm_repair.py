"""Batch LLM repair for reference titles that heuristics couldn't fix.

Sends all malformed references in one LLM call for title extraction.
"""

import json
import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from refcheck.llm.client import call_llm
from refcheck.models.reference import Reference
from refcheck.stages.parse_docx.title_repairer import detect_and_repair_bad_titles

if TYPE_CHECKING:
    from refcheck.llm.cost_tracker import CostTracker

logger = logging.getLogger(__name__)


class TitleRepairItem(BaseModel):
    """Single title repair result from LLM."""

    index: int
    title: str = ""


class TitleRepairResponse(BaseModel):
    """Batch LLM title repair response."""

    repairs: list[TitleRepairItem] = Field(default_factory=list)


async def repair_reference_titles(
    references: list[Reference],
    cost_tracker: "CostTracker | None" = None,
) -> list[Reference]:
    """Heuristic title repair, then one batched LLM call for the rest.

    Returns a new list; the input list is not modified.
    """
    refs = list(references)
    needs_llm = detect_and_repair_bad_titles(refs)
    if not needs_llm:
        return refs
    repaired = await batch_repair_titles(needs_llm, cost_tracker)
    for idx, title in repaired.items():
        if 0 <= idx < len(refs):
            refs[idx] = refs[idx].model_copy(
                update={"title": title, "repair_applied": "llm_title_repair"},
            )
    return refs


async def batch_repair_titles(
    references_with_bad_titles: list[tuple[int, Reference]],
    cost_tracker: "CostTracker | None" = None,
) -> dict[int, str]:
    """Send all malformed references to LLM for title extraction.

    Uses the "utility" role (no hard-coded model) and records cost on the
    pipeline's tracker. Returns a dict mapping reference index to title.
    """
    if not references_with_bad_titles:
        return {}

    variables: dict[str, str] = {
        "references_json": _build_references_json(references_with_bad_titles),
    }

    try:
        result = await call_llm(
            template="title_repair",
            variables=variables,
            output_model=TitleRepairResponse,
            role="utility",
            cost_tracker=cost_tracker,
            task="title_repair",
        )
        repaired: dict[int, str] = {}
        for item in result.repairs:
            if item.title and len(item.title) > 10:
                repaired[item.index] = item.title
                logger.info(
                    "LLM repaired title [%d]: '%s'",
                    item.index, item.title[:60],
                )
        return repaired
    except Exception as exc:
        logger.warning("LLM title repair failed: %s", exc)
        return {}


def _build_references_json(
    refs: list[tuple[int, Reference]],
) -> str:
    """Build JSON string of references for the prompt template."""
    items = []
    for idx, ref in refs:
        items.append({
            "index": idx,
            "raw_text": ref.raw_text[:500],
            "current_title": ref.title,
        })
    return json.dumps(items, indent=2)
