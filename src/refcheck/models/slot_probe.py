"""Structured output of the blind slot probe (V5.7 #15, verify_claims/slot_probe.py).

The probe shows the cited span with its relation / direction / population words
masked ("[SLOT 1]") and asks what the source states in each slot. Sent as a strict
JSON schema (all fields required, nullable ones as ``X | None``); field names avoid
"reasoning"/"thinking", which Claude may refuse to fill. The answer is never trusted
on its own: slot_probe_rules.differs compares it with the claim's words and the quote
must be found verbatim in the evidence pack.
"""

from pydantic import BaseModel, field_validator

_MAX_SLOTS = 3
_MAX_TEXT = 400


class SlotAnswer(BaseModel):
    """What the source states for one slot."""

    slot: int  # the slot number as shown ("[SLOT 2]" -> 2)
    answer: str  # the source's own words for the slot, or "not stated"
    passage_id: str | None  # "P3" / "A"; null when not stated
    quote: str | None  # verbatim words of that passage stating the answer

    @field_validator("answer", mode="after")
    @classmethod
    def _trim(cls, value: str) -> str:
        return " ".join(value.split())[:_MAX_TEXT]


class SlotProbeOutput(BaseModel):
    """One entry per slot, plus a short overall explanation."""

    slots: list[SlotAnswer]
    explanation: str

    @field_validator("slots", mode="after")
    @classmethod
    def _cap(cls, value: list[SlotAnswer]) -> list[SlotAnswer]:
        return value[:_MAX_SLOTS]
