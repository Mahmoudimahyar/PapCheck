"""Tests for reference repair pass (V2 — malformed DOCX entries)."""

from refcheck.stages.parse_docx.reference_repairer import (
    RepairEntry,
    repair_reference_list,
    summarize_repairs,
)


def test_merges_truncated_journal_front() -> None:
    """Fragment 'Front' merges with next entry."""
    raw = ["Front", "iers in Bioengineering\nLark, J. et al. (2024)"]
    result = repair_reference_list(raw)
    assert len(result) == 1
    assert "Front" in result[0].text
    assert result[0].repair_type in ("merged_fragment", "merged_journal_prefix")


def test_removes_number_prefix() -> None:
    """Leading reference number is stripped."""
    raw = ["68\ndoi: 10.5555/synth.a.10001\nRuse, A. et al."]
    result = repair_reference_list(raw)
    assert result[0].text.startswith("doi:")
    assert result[0].repair_type == "removed_number_prefix"


def test_merges_truncated_circ() -> None:
    """Fragment 'Circ' merges with next entry."""
    raw = ["Circ", "ulation\nFenn, L. et al. (2019)"]
    result = repair_reference_list(raw)
    assert len(result) == 1
    assert "Circ" in result[0].text or "ulation" in result[0].text


def test_no_repair_for_normal_entries() -> None:
    """Well-formed entries pass through unchanged."""
    raw = ["Smith, J. et al. (2020). Title of paper. Nature, 580, 123-130."]
    result = repair_reference_list(raw)
    assert len(result) == 1
    assert result[0].repair_type == "none"


def test_handles_int_prefix() -> None:
    """Fragment 'Int' merges with next entry."""
    raw = [
        "Int",
        "ernational Journal of...\nTull, R. (2012). Effects of a model drug on synthetic grafts",
    ]
    result = repair_reference_list(raw)
    assert len(result) == 1
    assert "Int" in result[0].text


def test_multiple_entries_mixed() -> None:
    """Mix of normal and malformed entries."""
    raw = [
        "Smith, J. et al. (2020). Title of paper. Nature, 580, 123-130.",
        "Front",
        "iers in Bioengineering\nLark, J. et al. (2024)",
        "68\ndoi: 10.5555/synth.a.10001\nRuse, A. et al.",
        "Jones, A. (2019). Another paper. Science, 10, 1-5.",
    ]
    result = repair_reference_list(raw)
    assert len(result) == 4  # 5 raw → 4 (one merge)
    assert result[0].repair_type == "none"
    assert result[1].repair_type in ("merged_fragment", "merged_journal_prefix")
    assert result[2].repair_type == "removed_number_prefix"
    assert result[3].repair_type == "none"


def test_summarize_repairs() -> None:
    """Summary string reports counts correctly."""
    entries = [
        RepairEntry(text="a", repair_type="none"),
        RepairEntry(text="b", repair_type="merged_fragment"),
        RepairEntry(text="c", repair_type="removed_number_prefix"),
        RepairEntry(text="d", repair_type="merged_journal_prefix"),
    ]
    summary = summarize_repairs(entries)
    assert "3" in summary  # 3 repaired
    assert "4" in summary  # 4 total


def test_fragment_at_end_of_list() -> None:
    """Fragment at end with no next entry stays as-is."""
    raw = ["Front"]
    result = repair_reference_list(raw)
    assert len(result) == 1
    assert result[0].repair_type == "none"


def test_empty_input() -> None:
    """Empty input returns empty."""
    result = repair_reference_list([])
    assert result == []
