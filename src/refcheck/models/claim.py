"""Claim and atomic claim data models for V1 claim extraction."""

from typing import Literal

from pydantic import BaseModel, Field

from refcheck.models.evidence import ClaimLocation

ClaimQuality = Literal["ok", "fragment"]


class Claim(BaseModel):
    """A claim-citation pair extracted from the manuscript."""

    id: int
    manuscript_text: str = ""
    extracted_claim: str = ""
    paragraph_text: str = ""
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
    atomic_claims: list[str] = Field(default_factory=list)
    location: ClaimLocation | None = None
    # V5: references cited together in the same sentence (1 = cited alone)
    co_cited_count: int = Field(default=1, ge=1)
    # Part of the sentence THIS reference is cited for (inline markers narrow
    # it, e.g. "A does X (Ref1) and Y (Ref2)" -> Ref2 is cited for "Y").
    # Equals extracted_claim when the reference covers the whole sentence;
    # "" only on claims created before this field existed.
    cited_for: str = ""
    # "fragment" = the citing sentence looks incomplete (no finite verb, a bare
    # gerund phrase, a heading...). Still verified; show "Claim text appears incomplete".
    claim_quality: ClaimQuality = "ok"
    # The in-text citation could match several references (e.g. "Wang et al.,
    # 2024" with Wang 2024a/2024b in the list); reference_ids holds the best guess.
    mapping_ambiguous: bool = False
    candidate_reference_ids: list[int] = Field(default_factory=list)


class AtomicClaim(BaseModel):
    """A single verifiable assertion decomposed from a compound claim (V2)."""

    id: int
    parent_claim_id: int
    text: str = ""
    verifiable: bool = True
    tags: list[str] = Field(default_factory=list)
