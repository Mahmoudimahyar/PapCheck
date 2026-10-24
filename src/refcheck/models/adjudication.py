"""Structured output of the element adjudicator (verify_claims/adjudicate.py).

The adjudicator answers one narrow question per element a partial verdict
listed as unsupported: is it stated in the source, stated by a co-cited
reference, only the author's framing, only wording, or a genuine gap (absent,
broadened scope, overstated certainty, contradicted)? Sent as
a strict JSON schema (all fields required, nullable ones as ``X | None``);
field names avoid "reasoning"/"thinking", which Claude may refuse to fill.
The model's category is never trusted on its own: the code clears an element
only under the rule in ``adjudicate_rules.decide`` (exact quote, no quantifier).
The co-cited union check after it (``CocitedOutput``) asks, for the elements still
absent, whether a co-cited reference's full-text passage states them; its rule is
``cocited_union_rules.decide_union`` and ``UnionSummary`` records what it did.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

ElementCategory = Literal[
    "stated", "cocited", "framing", "wording", "absent", "broadened", "overstated",
    "contradicted",
]
# Categories that can clear an element (subject to the code's checks).
CLEARING_CATEGORIES: frozenset[str] = frozenset({"stated", "cocited", "framing", "wording"})

_MAX_ELEMENTS = 6
_MAX_TEXT = 400


class ElementCheck(BaseModel):
    """The adjudicator's answer for one element (same order as the input list)."""

    element: str
    category: ElementCategory
    passage_id: str | None  # "P3" / "A" for stated / wording; the co-cited number for cocited
    quote: str | None  # verbatim words from that passage / co-cited abstract
    note: str  # one short sentence (required for framing)

    @field_validator("element", "note", mode="after")
    @classmethod
    def _trim(cls, value: str) -> str:
        return " ".join(value.split())[:_MAX_TEXT]


class AdjudicateOutput(BaseModel):
    """One entry per input element, plus a short overall explanation."""

    elements: list[ElementCheck]
    explanation: str  # never "reasoning": Claude may refuse "reasoning extraction"

    @field_validator("elements", mode="after")
    @classmethod
    def _cap(cls, value: list[ElementCheck]) -> list[ElementCheck]:
        return value[:_MAX_ELEMENTS]


# --- Co-cited full-text union check (verify_claims/cocited_union*.py) ---------------------
CocitedCategory = Literal["cocited", "absent"]
UnionOutcome = Literal["cleared", "partial", "held", "unchanged", "error", "skipped"]


class CocitedCheck(BaseModel):
    """The union check's answer for one element still called absent for THIS reference."""

    element: str
    category: CocitedCategory
    passage_id: str | None  # a co-cited passage ("R12-P3") for cocited, else null
    quote: str | None  # verbatim words of that passage
    note: str

    @field_validator("element", "note", mode="after")
    @classmethod
    def _trim(cls, value: str) -> str:
        return " ".join(value.split())[:_MAX_TEXT]


class CocitedOutput(BaseModel):
    """One entry per element asked about, plus a short overall explanation."""

    elements: list[CocitedCheck]
    explanation: str

    @field_validator("elements", mode="after")
    @classmethod
    def _cap(cls, value: list[CocitedCheck]) -> list[CocitedCheck]:
        return value[:_MAX_ELEMENTS]


class UnionSummary(BaseModel):
    """What the co-cited union check did for one pair (eval records, logs).

    ``skipped``: elements were absent and a co-cited source existed, but this
    reference did not support its own share (no validated quote), so no call was made.
    """

    outcome: UnionOutcome
    model_id: str = ""
    cleared: dict[str, int] = Field(default_factory=dict)  # element -> co-cited ref number
    surviving: list[str] = Field(default_factory=list)
    refs: list[int] = Field(default_factory=list)  # co-cited references searched
    error: str | None = None
