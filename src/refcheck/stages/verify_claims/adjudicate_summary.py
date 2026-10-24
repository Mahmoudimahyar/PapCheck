"""What the element adjudicator did for one pair (eval records, logs; adjudicate_apply.py).

Outcomes: cleared / partial / held / unchanged / error, and V5.7 #13 "tangential"
(adjudicate_tangential.py: every cleared element was stated only by a co-cited
reference, so the citation is shown as not supported).
"""

from collections import Counter
from typing import Literal

from pydantic import BaseModel, Field

from refcheck.models.adjudication import UnionSummary
from refcheck.stages.verify_claims.adjudicate import Adjudication

Outcome = Literal["cleared", "partial", "held", "unchanged", "error", "tangential"]


class AdjudicationSummary(BaseModel):
    """What the adjudicator did for one pair (eval records, logs)."""

    outcome: Outcome
    model_id: str = ""
    categories: dict[str, int] = Field(default_factory=dict)  # the model's categories
    cleared: list[str] = Field(default_factory=list)
    surviving: list[str] = Field(default_factory=list)
    error: str | None = None
    union: UnionSummary | None = None  # the co-cited union check after it (cocited_union.py)


def summarize(adj: Adjudication, held: bool = False, tangential: bool = False,
              ) -> AdjudicationSummary:
    cleared, surviving = adj.cleared, adj.surviving
    outcome: Outcome = ("error" if not adj.ok else "tangential" if tangential
                        else "unchanged" if not cleared
                        else "partial" if surviving else "held" if held else "cleared")
    return AdjudicationSummary(
        outcome=outcome, model_id=adj.meta.model_id, error=adj.meta.error,
        categories=dict(Counter(d.category for d in adj.decisions)),
        cleared=[d.element for d in cleared], surviving=[d.element for d in surviving])
