"""Pydantic models for the OpenAI Decisions API wrapper."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from refcheck.llm.errors import LLMError
from refcheck.llm.types import ErrorKind


class DecisionQuestion(BaseModel):
    """One question for the Decisions API (predicates preferred)."""

    name: str = Field(min_length=1, max_length=64)
    instructions: str = Field(min_length=1)
    type: Literal["predicate", "choice"] = "predicate"
    choices: list[str] | None = None

    @model_validator(mode="after")
    def _check_choices(self) -> "DecisionQuestion":
        if self.type == "choice":
            if not self.choices or len(self.choices) < 2:
                raise ValueError("choice questions need at least 2 choices")
            if len(set(self.choices)) != len(self.choices):
                raise ValueError("choice values must be unique")
        return self

    def to_api(self) -> dict[str, object]:
        """Request payload for litellm.decisions."""
        payload: dict[str, object] = {
            "type": self.type, "name": self.name, "instructions": self.instructions,
        }
        if self.type == "choice":
            payload["choices"] = [{"value": c} for c in self.choices or []]
        return payload


class DecisionAnswer(BaseModel):
    """Answer to one question; refused answers carry no probability."""

    name: str
    type: Literal["predicate", "choice", "refusal"]
    probability: float | None = None
    choice: str | None = None
    probabilities: dict[str, float] = Field(default_factory=dict)
    refused: bool = False


class DecisionResult(BaseModel):
    """All answers for one input (merged across chunks)."""

    model: str
    answers: dict[str, DecisionAnswer] = Field(default_factory=dict)
    input_tokens: int = 0
    cached_input_tokens: int = 0
    latency_ms: int = 0
    cost_usd: float = 0.0
    requests: int = 0

    @property
    def refused(self) -> list[str]:
        """Names of refused (or missing) questions."""
        return [name for name, answer in self.answers.items() if answer.refused]

    def probability(self, name: str) -> float | None:
        """Predicate probability, None when refused/absent."""
        answer = self.answers.get(name)
        return None if answer is None or answer.refused else answer.probability


class DecisionError(LLMError):
    """Decisions API call failed (caller decides: skip screen for the pair)."""

    def __init__(self, message: str, kind: ErrorKind = "other",
                 model_id: str | None = None) -> None:
        super().__init__(message, kind, model_id)
