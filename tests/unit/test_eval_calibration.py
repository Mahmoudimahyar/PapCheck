"""Unit tests for the fixed-sequence Clopper-Pearson calibration of t_accept."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "eval"))

import calibrate_screen  # noqa: E402
from eval_calibration import choose, default_grid, merge_records, scan  # noqa: E402
from eval_models import ItemRecord, LayerRecord, ScreenRecord  # noqa: E402

from refcheck.stages.verify_claims.calibration import load_thresholds  # noqa: E402


def item(idx: int, s: float, problem: bool, cosign: bool = True, gates: tuple[str, ...] = (),
         with_screen: bool = True, with_verifier: bool = True) -> ItemRecord:
    layers = [LayerRecord(layer="verifier", role="verifier",
                          verdict="supported" if cosign else "not_supported",
                          quote_roles=["supports"] if cosign else [])] if with_verifier else []
    return ItemRecord(
        id=f"i{idx}", dataset="citation_integrity", gold_label="not_supported" if problem
        else "supported", gold_binary="problem" if problem else "ok", mode="cascade",
        screen=ScreenRecord(s=s, model="gpt-6-luna-decisions") if with_screen else None,
        gate_failures=list(gates), layers=layers)


def population(clean_high: int, bad_mid: int, clean_mid: int, bad_low: int) -> list[ItemRecord]:
    """clean pairs at s=0.995, problems at s=0.9, clean at s=0.9, problems at s=0.6."""
    out = [item(i, 0.995, False) for i in range(clean_high)]
    out += [item(1000 + i, 0.9, True) for i in range(bad_mid)]
    out += [item(2000 + i, 0.9, False) for i in range(clean_mid)]
    out += [item(3000 + i, 0.6, True) for i in range(bad_low)]
    return out


def test_default_grid_is_descending_099_to_050() -> None:
    grid = default_grid()
    assert grid[0] == 0.99 and grid[-1] == 0.5 and len(grid) == 50
    assert all(a > b for a, b in zip(grid, grid[1:], strict=False))


def test_scan_picks_lowest_threshold_before_first_failure() -> None:
    records = population(clean_high=150, bad_mid=1, clean_mid=200, bad_low=40)
    rows = scan(records, [0.99, 0.95, 0.9, 0.8, 0.7, 0.6, 0.5], alpha=0.03)
    by_t = {r.t_accept: r for r in rows}
    assert by_t[0.99].n_cleared == 150 and by_t[0.99].passed
    assert by_t[0.9].n_cleared == 351 and by_t[0.9].problems == 1 and by_t[0.9].passed
    assert not by_t[0.6].passed  # 41 problems among 391
    chosen = choose(rows)
    assert chosen is not None and chosen.t_accept == 0.7  # 0.8 and 0.7 clear the same set


def test_fixed_sequence_stops_at_first_failure_even_if_later_passes() -> None:
    # Too few cleared pairs at 0.99 -> the bound fails; testing must stop there.
    records = population(clean_high=20, bad_mid=0, clean_mid=500, bad_low=0)
    rows = scan(records, [0.99, 0.9], alpha=0.03)
    assert not rows[0].passed
    assert not rows[1].passed  # would pass on its own (0/520) but is never tested
    assert rows[1].upper_bound <= 0.03
    assert choose(rows) is None


def test_gates_and_cosign_are_part_of_the_rule() -> None:
    records = [item(i, 0.999, False) for i in range(120)]
    records += [item(500 + i, 0.999, True, gates=("numeric_claim",)) for i in range(30)]
    records += [item(800 + i, 0.999, True, cosign=False) for i in range(30)]
    with_cosign = scan(records, [0.99], alpha=0.03, cosign=True)[0]
    assert (with_cosign.n_cleared, with_cosign.problems) == (120, 0)
    assert with_cosign.passed
    without = scan(records, [0.99], alpha=0.03, cosign=False)[0]
    assert (without.n_cleared, without.problems) == (150, 30)
    assert not without.passed


def test_merge_takes_screen_and_verifier_from_different_runs() -> None:
    screen_run = [item(1, 0.99, False, with_verifier=False)]
    verifier_run = [item(1, 0.0, False, with_screen=False)]
    merged = merge_records([screen_run, verifier_run])
    assert len(merged) == 1
    assert merged[0].screen is not None and merged[0].screen.s == 0.99
    assert [lay.layer for lay in merged[0].layers] == ["verifier"]


def _write_run(path: Path, records: list[ItemRecord]) -> Path:
    path.mkdir(parents=True)
    (path / "items.jsonl").write_text("\n".join(r.model_dump_json() for r in records),
                                      encoding="utf-8")
    return path


def test_main_writes_a_file_the_app_loads(tmp_path: Path,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    run_dir = _write_run(tmp_path / "run", population(150, 1, 200, 40))
    out = tmp_path / "screen.json"
    result = calibrate_screen.main(["--run", str(run_dir), "--out", str(out)])
    # default grid (step 0.01): s=0.6 problems enter at 0.60, so 0.61 is the lowest pass
    assert result.enabled and result.auto_clear and result.t_accept == pytest.approx(0.61)
    raw = json.loads(out.read_text(encoding="utf-8"))
    assert raw["meta"]["screen_model"] == "gpt-6-luna-decisions"
    assert raw["meta"]["n"] == 391 and raw["meta"]["cosign"] is True
    assert raw["meta"]["question_template_hash"]
    monkeypatch.setenv("REFCHECK_SCREEN_CALIBRATION", str(out))
    monkeypatch.delenv("REFCHECK_SCREEN_T_ACCEPT", raising=False)
    monkeypatch.delenv("REFCHECK_SCREEN_ENABLED", raising=False)
    monkeypatch.delenv("REFCHECK_PRIVACY_PROFILE", raising=False)
    thresholds = load_thresholds()
    assert thresholds.t_accept == pytest.approx(0.61)
    assert thresholds.enabled and thresholds.t_contra == 0.5 and thresholds.source == str(out)


def test_main_disables_auto_clear_when_nothing_passes(tmp_path: Path) -> None:
    run_dir = _write_run(tmp_path / "run", population(10, 5, 10, 5))
    out = tmp_path / "screen.json"
    result = calibrate_screen.main(["--run", str(run_dir), "--out", str(out)])
    # The screen keeps running (ranking + conflict check); only auto-clear is off.
    assert result.enabled and not result.auto_clear
    assert json.loads(out.read_text(encoding="utf-8"))["meta"]["reason"]


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    run_dir = _write_run(tmp_path / "run", population(150, 0, 0, 0))
    out = tmp_path / "screen.json"
    calibrate_screen.main(["--run", str(run_dir), "--out", str(out), "--dry-run"])
    assert not out.exists()
