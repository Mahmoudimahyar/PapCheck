"""Claim and atomic claim data models for V1 claim extraction."""

from typing import Literal

from pydantic import BaseModel, Field


class Claim(BaseModel):
    """A claim-citation pair extracted from the manuscript."""

    id: int
    manuscript_text: str = ""
    extracted_claim: str = ""
    claim_type: Literal[
        "factual",
        "methodological",
        "background",
        "attribution",
        "contrast",
        "interpretive",
    ] = "factual"
    reference_ids: list[int] = Field(default_factory=list)
    priority: Literal["high", "medium", "low"] = "medium"
    section_heading: str = ""


class AtomicClaim(BaseModel):
    """A single verifiable assertion decomposed from a compound claim (V2)."""

    id: int
    parent_claim_id: int
    text: str = ""
    verifiable: bool = True
    tags: list[str] = Field(default_factory=list)
