"""Claim and atomic claim data models (stub for V1)."""

from typing import Literal

from pydantic import BaseModel, Field


class Claim(BaseModel):
    """A claim-citation pair extracted from the manuscript (V1 feature)."""

    id: int
    reference_id: int
    manuscript_text: str = ""
    extracted_claim: str = ""
    claim_type: Literal[
        "factual",
        "methodological",
        "background",
        "attribution",
        "contrast",
        "interpretive",
        "unknown",
    ] = "unknown"
    priority: Literal["high", "medium", "low"] = "medium"
    section: str | None = None


class AtomicClaim(BaseModel):
    """A single verifiable assertion decomposed from a compound claim (V2)."""

    id: int
    parent_claim_id: int
    text: str = ""
    verifiable: bool = True
    tags: list[str] = Field(default_factory=list)
