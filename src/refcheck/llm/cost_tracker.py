"""Track LLM API costs across the pipeline."""

import logging
import threading
from collections import defaultdict

from pydantic import BaseModel, Field

from refcheck.llm.model_registry import ModelConfig

logger = logging.getLogger(__name__)


class LLMCallRecord(BaseModel):
    """Record of a single LLM API call with cost data."""

    model_name: str
    model_id: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    task: str
    tier: int
    response_time_ms: int = 0


class CostLimitExceededError(Exception):
    """Raised when cumulative LLM cost exceeds the configured limit."""


class CostTracker:
    """Thread-safe tracker for LLM call costs and statistics."""

    def __init__(self, max_cost: float = 50.0) -> None:
        self.max_cost = max_cost
        self.records: list[LLMCallRecord] = []
        self._lock = threading.Lock()

    def record(
        self,
        model: ModelConfig,
        input_tokens: int,
        output_tokens: int,
        task: str,
        response_time_ms: int = 0,
    ) -> LLMCallRecord:
        """Record a call and check cost limit. Returns the record."""
        cost = (
            input_tokens / 1_000_000 * model.input_cost_per_m
            + output_tokens / 1_000_000 * model.output_cost_per_m
        )
        entry = LLMCallRecord(
            model_name=model.name,
            model_id=model.litellm_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=round(cost, 6),
            task=task,
            tier=model.tier,
            response_time_ms=response_time_ms,
        )
        with self._lock:
            self.records.append(entry)
            total = self.total_cost
        if total > self.max_cost:
            raise CostLimitExceededError(
                f"${total:.2f} exceeds limit ${self.max_cost:.2f}",
            )
        return entry

    @property
    def total_cost(self) -> float:
        """Sum of all recorded costs."""
        return sum(r.cost_usd for r in self.records)

    @property
    def total_calls(self) -> int:
        """Total number of LLM calls."""
        return len(self.records)

    def summary(self) -> "CostSummary":
        """Return structured cost breakdown."""
        by_model: dict[str, float] = defaultdict(float)
        by_task: dict[str, float] = defaultdict(float)
        by_tier: dict[int, int] = defaultdict(int)

        for r in self.records:
            by_model[r.model_name] += r.cost_usd
            by_task[r.task] += r.cost_usd
            by_tier[r.tier] += 1

        return CostSummary(
            total_usd=round(self.total_cost, 4),
            total_calls=self.total_calls,
            by_model={k: round(v, 4) for k, v in by_model.items()},
            by_task={k: round(v, 4) for k, v in by_task.items()},
            by_tier=dict(by_tier),
        )


class CostSummary(BaseModel):
    """Structured cost summary for reporting and API responses."""

    total_usd: float = 0.0
    total_calls: int = 0
    by_model: dict[str, float] = Field(default_factory=dict)
    by_task: dict[str, float] = Field(default_factory=dict)
    by_tier: dict[int, int] = Field(default_factory=dict)
