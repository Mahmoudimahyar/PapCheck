"""Eval plumbing of V5.6 credit panels: gold rows get the production panel (no network)."""

import json
import sqlite3
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "eval"))

import eval_credit  # noqa: E402
import eval_dry_run  # noqa: E402
import run_eval  # noqa: E402
from eval_gold import gold_claim, production_query  # noqa: E402
from eval_models import ItemRecord  # noqa: E402
from gold_models import GoldRow  # noqa: E402

from refcheck.models.claim import Claim  # noqa: E402
from refcheck.stages.verify_claims.credit import PANEL_PREFIX, panel_of  # noqa: E402
from tests.unit.credit_fakes import (  # noqa: E402
    LEGEND,
    PANEL_A,
    PANEL_C,
    ROE,
    credit_claim,
    strip,
)
from tests.unit.test_eval_gold_run import gold_row, make_pdf, write_rows  # noqa: E402

_UNION = f"{strip(PANEL_A)}. {strip(PANEL_C)}"


@pytest.fixture(autouse=True)
def _fresh_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(eval_credit, "DEFAULT_DB", tmp_path / "no-app.db")  # never the real DB
    eval_credit.session_claims.cache_clear()
    yield
    eval_credit.session_claims.cache_clear()


def credit_row(**extra: object) -> GoldRow:
    fields: dict[str, object] = {
        "id": "v49-credit", "sentence": ROE, "claim": ROE, "cited_for": "Adapted from Roe et al",
        "paragraph": LEGEND, "co_cited_count": 1, "co_cited_refs": [], "gold_label": "supported",
        "gold_binary": "ok", "gold_partial_type": "", "session_id": "sess_t", "claim_number": 7}
    fields.update(extra)
    return gold_row(**fields)


def _db(path: Path, *claims: Claim) -> Path:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE claims (session_id TEXT, claim_number INTEGER, manuscript_text "
                "TEXT, extracted_claim TEXT, cited_for TEXT, paragraph_text TEXT, "
                "location_json TEXT)")
    con.executemany("INSERT INTO claims VALUES (?, ?, ?, ?, ?, ?, ?)", [
        ("sess_t", c.id, c.manuscript_text, c.extracted_claim, c.cited_for, c.paragraph_text,
         c.location.model_dump_json() if c.location else None) for c in claims])
    con.commit()
    con.close()
    return path


def _session_db(path: Path) -> Path:
    return _db(path, credit_claim(5, base=100, nth=0), credit_claim(7, base=100, nth=1))


def test_session_offsets_pick_the_rows_own_panel(tmp_path: Path) -> None:
    db = _session_db(tmp_path / "rc.db")
    raw = credit_claim(1)
    assert panel_of(eval_credit.gold_panel_claim(credit_row(), raw, db)) == strip(PANEL_C)
    first = eval_credit.gold_panel_claim(credit_row(claim_number=5), raw, db)
    assert panel_of(first) == strip(PANEL_A)


def test_gold_claim_reads_the_default_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(eval_credit, "DEFAULT_DB", _session_db(tmp_path / "app.db"))
    assert panel_of(gold_claim(credit_row(), 1)) == strip(PANEL_C)


def test_without_the_session_every_identical_credit_panel_is_used(tmp_path: Path) -> None:
    claim = eval_credit.gold_panel_claim(credit_row(session_id="sess_missing"), credit_claim(1),
                                         tmp_path / "none.db")
    assert panel_of(claim) == _UNION
    assert eval_credit.session_claims("", str(tmp_path / "none.db")) == ()


def test_unreadable_db_is_not_fatal(tmp_path: Path) -> None:
    broken = tmp_path / "broken.db"
    broken.write_text("not a database", encoding="utf-8")
    assert eval_credit.session_claims("sess_t", str(broken)) == ()


def test_gold_claim_keeps_its_text_and_queries_the_panel() -> None:
    claim = gold_claim(credit_row(session_id=""), 3)
    assert claim.manuscript_text == ROE and claim.extracted_claim == ROE
    assert claim.cited_for == PANEL_PREFIX + _UNION
    assert production_query(claim).startswith(PANEL_PREFIX + "(A) Fluorescence")


def test_ordinary_rows_are_unchanged() -> None:
    assert gold_claim(gold_row(), 3).cited_for == "Drug X reduces inflammation in mice"


async def test_dry_run_on_a_credit_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = make_pdf(tmp_path / "paper.pdf")
    data = write_rows(tmp_path / "gold.jsonl", credit_row(pdf_path=str(pdf), session_id=""))
    seen: list[str] = []
    fake = eval_dry_run.fake_call_llm_raw

    async def spy(template: str, variables: dict[str, object], *args: object,
                  **kwargs: object) -> object:
        seen.append(str(variables.get("cited_for", "")))
        return await fake(template, variables, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(eval_dry_run, "fake_call_llm_raw", spy)
    monkeypatch.setattr(run_eval, "load_dotenv", lambda *a, **k: None)
    cfg = eval_dry_run.parse_cli(["--dataset", str(data), "--dry-run", "--run-name", "c",
                                  "--results-dir", str(tmp_path)], None)
    result = await run_eval.run(cfg)
    assert result.meta.dry_run and result.meta.total_cost_usd == 0.0
    record = ItemRecord.model_validate_json(
        (tmp_path / "c" / "items.jsonl").read_text(encoding="utf-8"))
    assert record.error is None and record.verdict != "cannot_verify"
    assert seen and all(part == PANEL_PREFIX + _UNION for part in seen if part)
    assert json.loads(data.read_text(encoding="utf-8"))["cited_for"] == "Adapted from Roe et al"
