"""The V5.5 output schema of the verifier / judge / confirm layers (default mode).

REFCHECK_STRICT_CLEARANCE=off (default) sends the model this schema: no quote
``states`` and no ``dismissed`` list. Class names, field order, types and
docstrings equal the V5.5 ``EvidenceQuote`` / ``JudgeOutput`` exactly, because the
LLM cache key covers the schema sent to the model and the output model's name
(llm/structured.py): the default mode reuses the cached V5.5 answers. Parsed
answers are converted to ``verification.JudgeOutput`` (V5.6 fields at their
defaults) by ``stages/verify_claims/clearance_mode.py``; validation stays there.
"""

from typing import Literal

from pydantic import BaseModel, Field

from refcheck.models.partial_types import BenignNote, PartialType
from refcheck.models.verification import LayerVerdict, ProblemType


class EvidenceQuote(BaseModel):
    """A verbatim quote an LLM layer cites from the evidence pack."""

    passage_id: str  # "A" or "P3" — ids shown in the pack
    text: str  # verbatim, <= 60 words
    role: Literal["supports", "contradicts", "closest"]


class JudgeOutput(BaseModel):
    """Structured output shared by the verifier (L2), judge (L3) and confirm (L4) layers.

    Sent as a strict JSON schema; strict mode drops numeric/length limits,
    so they are enforced leniently here (clamp/truncate, never reject).
    """

    verdict: LayerVerdict
    severity: Literal["none", "minor", "major"]
    problem_type: ProblemType
    confidence: float  # self-reported; stored, never used for routing
    quotes: list[EvidenceQuote]
    explanation: str  # never "reasoning"/"thinking": Claude may refuse "reasoning extraction"
    missing: str | None
    # Taxonomy v1.1 (models/partial_types.py). Defaults keep older cached outputs parseable.
    partial_type: PartialType = "none"
    unsupported_elements: list[str] = Field(default_factory=list)  # <=5 short phrases
    benign_notes: list[BenignNote] = Field(default_factory=list)  # concerns considered + dismissed
