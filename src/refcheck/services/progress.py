"""Pipeline stage progress tracking with ETA computation."""

import logging
import time
from collections import deque

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ProgressSnapshot(BaseModel):
    """Point-in-time progress for a pipeline stage."""

    current: int
    total: int
    percent: float  # 0.0 to 100.0
    rate: float  # items per second
    elapsed_seconds: float
    estimated_remaining_seconds: float


class ProgressTracker:
    """Track progress for a pipeline stage with rolling-window ETA.

    Uses a rolling window of the last 20 tick timestamps to compute
    a smooth rate, avoiding ETA jitter from individual slow items.
    """

    def __init__(self, total: int, stage_name: str) -> None:
        self.total = total
        self.stage_name = stage_name
        self.completed = 0
        self._start_time = time.monotonic()
        self._tick_times: deque[float] = deque(maxlen=20)

    def tick(self) -> ProgressSnapshot:
        """Record one item completed and return current snapshot."""
        now = time.monotonic()
        self._tick_times.append(now)
        self.completed += 1
        return self._snapshot_at(now)

    def snapshot(self) -> ProgressSnapshot:
        """Return current snapshot without incrementing."""
        return self._snapshot_at(time.monotonic())

    def _snapshot_at(self, now: float) -> ProgressSnapshot:
        elapsed = now - self._start_time
        rate = self._compute_rate(now)
        remaining = self.total - self.completed
        eta = remaining / rate if rate > 0 else 0.0
        pct = (
            round(self.completed / self.total * 100, 1)
            if self.total > 0
            else 0.0
        )
        return ProgressSnapshot(
            current=self.completed,
            total=self.total,
            percent=pct,
            rate=round(rate, 2),
            elapsed_seconds=round(elapsed, 1),
            estimated_remaining_seconds=round(eta, 1),
        )

    def _compute_rate(self, now: float) -> float:
        """Items/sec using rolling window for smooth ETA."""
        if len(self._tick_times) < 2:
            elapsed = now - self._start_time
            return self.completed / elapsed if elapsed > 0 else 0.0
        window = self._tick_times[-1] - self._tick_times[0]
        if window <= 0:
            return 0.0
        return (len(self._tick_times) - 1) / window

    def make_message(self) -> str:
        """Human-readable progress message."""
        if self.completed == 0:
            return f"Starting {self.stage_name}..."
        snap = self._snapshot_at(time.monotonic())
        eta_str = format_duration(snap.estimated_remaining_seconds)
        return (
            f"{self.stage_name}: {snap.current}/{snap.total} "
            f"(~{eta_str} remaining)"
        )


def format_duration(seconds: float) -> str:
    """Format seconds as human-readable duration."""
    seconds = max(0, seconds)
    if seconds < 60:
        return f"{int(seconds)}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes < 60:
        return f"{minutes}m {secs}s" if secs > 0 else f"{minutes}m"
    hours = int(minutes // 60)
    mins = minutes % 60
    return f"{hours}h {mins}m"
