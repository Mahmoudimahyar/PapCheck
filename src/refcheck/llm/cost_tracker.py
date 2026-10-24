"""Track LLM API costs across the pipeline (chat, decisions, embeddings)."""

import logging
import os
import threading
from collections import defaultdict

from pydantic import BaseModel, Field

from refcheck.llm.degradation import Degradation, describe
from refcheck.llm.model_spec import ModelSpec
from refcheck.llm.usage import TokenUsage, compute_cost

logger = logging.getLogger(__name__)


class LLMCallRecord(BaseModel):
    """Record of a single LLM API call with cost data."""

    model_name: str
    model_id: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    task: str
    tier: int = 0
    response_time_ms: int = 0
    role: str | None = None
    kind: str = "chat"
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0
    success: bool = True


class CostLimitExceededError(Exception):
    """Raised when cumulative LLM cost exceeds the configured limit."""


class CostSummary(BaseModel):
    """Structured cost summary for reporting and API responses."""

    total_usd: float = 0.0
    total_calls: int = 0
    failed_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cached_tokens: int = 0
    by_model: dict[str, float] = Field(default_factory=dict)
    by_task: dict[str, float] = Field(default_factory=dict)
    by_role: dict[str, float] = Field(default_factory=dict)
    calls_by_role: dict[str, int] = Field(default_factory=dict)
    by_tier: dict[int, int] = Field(default_factory=dict)
    # V5.8: role -> one sentence (cause, effect, fix) for roles that ran degraded
    degraded: dict[str, str] = Field(default_factory=dict)


_DEFAULT_MAX_COST_USD = 50.0


def _default_max_cost() -> float:
    raw = os.getenv("REFCHECK_MAX_COST_USD", "")
    try:
        return float(raw) if raw else _DEFAULT_MAX_COST_USD
    except ValueError:
        logger.warning("Ignoring invalid REFCHECK_MAX_COST_USD=%r", raw)
        return _DEFAULT_MAX_COST_USD


class CostTracker:
    """Thread-safe tracker for LLM call costs and statistics."""

    def __init__(self, max_cost: float | None = None) -> None:
        # Per-run budget: explicit argument, else REFCHECK_MAX_COST_USD, else $50.
        self.max_cost = max_cost if max_cost is not None else _default_max_cost()
        self.records: list[LLMCallRecord] = []
        self.degradations: dict[str, Degradation] = {}
        self.soft_failures: dict[str, int] = defaultdict(int)
        self._reserved: dict[str, float] = defaultdict(float)
        self._lock = threading.Lock()

    def note_degraded(self, item: Degradation) -> None:
        """Remember that a role ran degraded in this run: a persistent cause (billing,
        key) replaces a transient one, never the other way round."""
        with self._lock:
            old = self.degradations.get(item.role)
            if old is None or item.persistent or not old.persistent:
                self.degradations[item.role] = item

    def count_soft_failure(self, role: str) -> int:
        """One more transient failure of a soft role in this run; the new count."""
        with self._lock:
            self.soft_failures[role] += 1
            return self.soft_failures[role]

    def spent(self, role: str, models: set[str]) -> float:
        """USD spent by ``role`` on any of ``models`` (degraded-mode spending cap)."""
        with self._lock:
            return sum(r.cost_usd for r in self.records
                       if r.role == role and r.model_name in models)

    def reserve(self, role: str, models: set[str], cap: float, default: float) -> float | None:
        """Reserve one call's estimated cost (the mean of ``role``'s calls on ``models``,
        else ``default``) against ``cap``; None when spent + reserved already reach it.
        Release with ``release`` after the call (its real cost is recorded by then)."""
        with self._lock:
            costs = [r.cost_usd for r in self.records if r.role == role and r.model_name in models]
            if sum(costs) + self._reserved[role] >= cap:
                return None
            estimate = max(default, sum(costs) / len(costs)) if costs else default
            self._reserved[role] += estimate
            return estimate

    def release(self, role: str, amount: float) -> None:
        with self._lock:
            self._reserved[role] = max(0.0, self._reserved[role] - amount)

    def ensure_budget(self) -> None:
        """Raise BEFORE a call when the budget is already used up."""
        total = self.total_cost
        if total >= self.max_cost:
            raise CostLimitExceededError(
                f"${total:.2f} reached limit ${self.max_cost:.2f}",
            )

    def record_usage(self, spec: ModelSpec, usage: TokenUsage, task: str, role: str | None = None,
                     response_time_ms: int = 0, success: bool = True) -> LLMCallRecord:
        """Record one call priced from its ModelSpec (never raises)."""
        entry = LLMCallRecord(
            model_name=spec.id, model_id=spec.litellm_id,
            input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
            cost_usd=round(compute_cost(spec, usage), 8), task=task,
            response_time_ms=response_time_ms, role=role, kind=spec.kind,
            cached_input_tokens=usage.cached_input_tokens,
            cache_write_tokens=usage.cache_write_tokens, success=success,
        )
        with self._lock:
            self.records.append(entry)
        return entry

    def record(self, model: ModelSpec, input_tokens: int, output_tokens: int, task: str,
               response_time_ms: int = 0) -> LLMCallRecord:
        """Legacy API: record a call, then raise if over the limit."""
        usage = TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens)
        entry = self.record_usage(model, usage, task, response_time_ms=response_time_ms)
        total = self.total_cost
        if total > self.max_cost:
            raise CostLimitExceededError(
                f"${total:.2f} exceeds limit ${self.max_cost:.2f}",
            )
        return entry

    @property
    def total_cost(self) -> float:
        """Sum of all recorded costs."""
        with self._lock:
            return sum(r.cost_usd for r in self.records)

    @property
    def total_calls(self) -> int:
        """Total number of LLM calls."""
        return len(self.records)

    def summary(self) -> CostSummary:
        """Return structured cost breakdown."""
        with self._lock:
            records = list(self.records)
            degradations = dict(self.degradations)
        by_model: dict[str, float] = defaultdict(float)
        by_task: dict[str, float] = defaultdict(float)
        by_role: dict[str, float] = defaultdict(float)
        calls_by_role: dict[str, int] = defaultdict(int)
        by_tier: dict[int, int] = defaultdict(int)
        for r in records:
            by_model[r.model_name] += r.cost_usd
            by_task[r.task] += r.cost_usd
            by_tier[r.tier] += 1
            if r.role:
                by_role[r.role] += r.cost_usd
                calls_by_role[r.role] += 1
        return CostSummary(
            total_usd=round(sum(r.cost_usd for r in records), 4),
            total_calls=len(records),
            failed_calls=sum(1 for r in records if not r.success),
            total_input_tokens=sum(r.input_tokens for r in records),
            total_output_tokens=sum(r.output_tokens for r in records),
            total_cached_tokens=sum(r.cached_input_tokens for r in records),
            by_model={k: round(v, 6) for k, v in by_model.items()},
            by_task={k: round(v, 6) for k, v in by_task.items()},
            by_role={k: round(v, 6) for k, v in by_role.items()},
            calls_by_role=dict(calls_by_role),
            by_tier=dict(by_tier),
            degraded={role: describe(item) for role, item in degradations.items()},
        )
