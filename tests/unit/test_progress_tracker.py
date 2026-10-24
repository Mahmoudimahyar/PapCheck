"""Tests for the ProgressTracker and format_duration utilities."""


from refcheck.services.progress import ProgressTracker, format_duration


class TestProgressTracker:
    """ProgressTracker tick and snapshot behaviour."""

    def test_tick_increments_completed(self) -> None:
        tracker = ProgressTracker(total=100, stage_name="verify")
        snap = tracker.tick()
        assert snap.current == 1
        assert snap.total == 100
        assert snap.percent == 1.0

    def test_tick_computes_percent(self) -> None:
        tracker = ProgressTracker(total=4, stage_name="verify")
        tracker.tick()
        tracker.tick()
        snap = tracker.tick()
        assert snap.percent == 75.0

    def test_rate_after_multiple_ticks(self) -> None:
        tracker = ProgressTracker(total=100, stage_name="verify")
        for _ in range(5):
            tracker.tick()
        snap = tracker.tick()
        assert snap.rate > 0

    def test_eta_decreases_with_progress(self) -> None:
        tracker = ProgressTracker(total=10, stage_name="verify")
        snap1 = tracker.tick()
        for _ in range(5):
            tracker.tick()
        snap2 = tracker.tick()
        assert snap2.estimated_remaining_seconds <= snap1.estimated_remaining_seconds

    def test_zero_total_no_division_error(self) -> None:
        tracker = ProgressTracker(total=0, stage_name="empty")
        snap = tracker.tick()
        assert snap.percent == 0.0

    def test_snapshot_without_tick(self) -> None:
        tracker = ProgressTracker(total=10, stage_name="test")
        snap = tracker.snapshot()
        assert snap.current == 0
        assert snap.total == 10
        assert snap.percent == 0.0

    def test_make_message_initial(self) -> None:
        tracker = ProgressTracker(total=10, stage_name="verify_claims")
        msg = tracker.make_message()
        assert "Starting" in msg
        assert "verify_claims" in msg

    def test_make_message_after_tick(self) -> None:
        tracker = ProgressTracker(total=10, stage_name="verify_claims")
        tracker.tick()
        msg = tracker.make_message()
        assert "1/10" in msg
        assert "remaining" in msg

    def test_completed_all_gives_100_percent(self) -> None:
        tracker = ProgressTracker(total=5, stage_name="verify")
        for _ in range(5):
            tracker.tick()
        snap = tracker.snapshot()
        assert snap.percent == 100.0
        assert snap.estimated_remaining_seconds == 0.0


class TestFormatDuration:
    """Duration formatting utility."""

    def test_seconds(self) -> None:
        assert format_duration(26) == "26s"

    def test_zero(self) -> None:
        assert format_duration(0) == "0s"

    def test_negative_clamped(self) -> None:
        assert format_duration(-5) == "0s"

    def test_minutes_with_seconds(self) -> None:
        assert format_duration(90) == "1m 30s"

    def test_exact_minutes(self) -> None:
        assert format_duration(120) == "2m"

    def test_hours(self) -> None:
        assert format_duration(3720) == "1h 2m"

    def test_less_than_minute(self) -> None:
        assert format_duration(59) == "59s"
