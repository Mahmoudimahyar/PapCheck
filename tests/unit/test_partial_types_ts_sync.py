"""The UI's copy of the partial-type labels (frontend/src/lib/partial-types.ts) must match
the Python source of truth (models/partial_types.py, stages/generate_report/partial_findings.py),
so the Results page, the API and the DOCX report describe each type the same way."""

import re
from pathlib import Path

import pytest

from refcheck.models.partial_types import GUARD_LABELS, GUARD_ORDER, PARTIAL_TYPE_INFO
from refcheck.stages.generate_report.partial_findings import PARTIAL_KEYS, UNCLASSIFIED_INFO

_TS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "partial-types.ts"
_STRING = re.compile(r'"((?:[^"\\]|\\.)*)"')

pytestmark = pytest.mark.skipif(not _TS.exists(), reason="frontend sources not present")


def _source() -> str:
    return _TS.read_text(encoding="utf-8")


def _joined(expr: str) -> str:
    """Value of a TS string expression made of "..." + "..." literals."""
    return "".join(_STRING.findall(expr))


def _type_entry(key: str) -> tuple[str, str, str]:
    match = re.search(rf'\b{key}: \{{\s*label: (?P<label>"[^"]*"),\s*meaning:'
                      rf'(?P<meaning>(?:\s*"[^"]*"\s*\+?)+),\s*severity: "(?P<severity>\w+)"',
                      _source())
    assert match, f"{key} missing from {_TS.name}"
    return _joined(match["label"]), _joined(match["meaning"]), match["severity"]


def _guard_entry(key: str) -> tuple[str, str]:
    match = re.search(rf'\b{key}: \{{\s*label: (?P<label>"[^"]*"),\s*explanation:'
                      rf'(?P<expl>[^}}]*)\}}', _source())
    assert match, f"{key} missing from {_TS.name}"
    return _joined(match["label"]), _joined(match["expl"])


@pytest.mark.parametrize("key", list(PARTIAL_TYPE_INFO))
def test_type_labels_match(key: str) -> None:
    assert _type_entry(key) == PARTIAL_TYPE_INFO[key]


def test_unclassified_bucket_matches() -> None:
    assert _type_entry("unclassified") == UNCLASSIFIED_INFO


@pytest.mark.parametrize("key", list(GUARD_LABELS))
def test_guard_labels_match(key: str) -> None:
    assert _guard_entry(key) == GUARD_LABELS[key]


def test_order_matches() -> None:
    source = _source()
    type_positions = [source.index(f"\n  {key}: {{") for key in PARTIAL_KEYS]
    assert type_positions == sorted(type_positions)
    guard_positions = [source.index(f"\n  {key}: {{") for key in GUARD_ORDER]
    assert guard_positions == sorted(guard_positions)
