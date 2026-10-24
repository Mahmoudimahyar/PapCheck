"""Scoring hygiene (V5.7 #12): TPR/TNR, near/far misses, review tier, scoring groups,
merged gold rows scored on their most severe copy, and the ablation delta table."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "eval"))

from eval_ablation import delta_table, metrics_by_split  # noqa: E402
from eval_hygiene import compute_hygiene, group_records, hygiene_line  # noqa: E402
from eval_metrics import summarize  # noqa: E402
from eval_models import ItemRecord, RunMeta  # noqa: E402
from gold_db import DbVerification, SessionData  # noqa: E402
from gold_models import GoldRow, pair_id  # noqa: E402
from gold_recorded import find_verification  # noqa: E402

GOLD_BINARY = {"supported": "ok"}


def rec(gold: str, verdict: str, **extra: object) -> ItemRecord:
    return ItemRecord.model_validate({
        "id": extra.pop("id", f"{gold}-{verdict}"), "dataset": "d", "gold_label": gold,
        "gold_binary": GOLD_BINARY.get(gold, "problem"), "mode": "cascade",
        "verdict": verdict, **extra})


def test_near_and_far_misses_and_rates() -> None:
    records = [rec("partially_supported", "supported", needs_review=True),
               rec("partially_supported", "supported"),
               rec("not_supported", "supported", check_first=True),
               rec("supported", "partially_supported"), rec("supported", "contradicted"),
               rec("supported", "supported", needs_review=True), rec("supported", "supported"),
               rec("partially_supported", "not_supported"),
               rec("partially_supported", "partially_supported"),
               rec("supported", "error")]  # unscored
    h = compute_hygiene(records)
    assert h is not None
    assert (h.near_missed, h.far_missed, h.near_over, h.far_over, h.severity_errors) == (
        2, 1, 1, 1, 1)
    assert h.tpr_n == "2/5" and h.tnr_n == "2/4"
    assert h.missed_partial_surfaced == "1/2" and h.missed_problem_surfaced == "2/3"
    assert h.review_tier_recall_partial == 3 / 4 and h.review_tier_recall_problem == 4 / 5
    assert h.review_load == "3/5"  # supported verdicts carrying a review flag
    assert "missed near 2 far 1" in hygiene_line("h", h)
    assert compute_hygiene([rec("supported", "error")]) is None


def test_groups_report_flagged_rows_and_splits_apart() -> None:
    records = [rec("supported", "supported", id="a", split="dev", gold_source="review_A"),
               rec("not_supported", "supported", id="b", split="test",
                   eval_flags=["etiquette"], subset_role="fn"),
               rec("supported", "partially_supported", id="c", split="test",
                   eval_flags=["label_noise", "etiquette"], subset_role="fp")]
    groups = group_records(records)
    assert [r.id for r in groups["clean"]] == ["a"]
    assert [r.id for r in groups["flag:etiquette"]] == ["b", "c"]
    assert set(groups) == {"clean", "flag:etiquette", "flag:label_noise", "role:fn", "role:fp",
                           "source:review_A", "split:dev", "split:test"}
    assert "clean" not in group_records([rec("supported", "supported", split="dev")])
    meta = RunMeta(run_name="r", mode="cascade", dataset="d", split="all", dataset_path="p",
                   n_items=3, source="auto", use_embeddings=False, concurrency=1,
                   started_at="now")
    summary = summarize(records, meta)
    assert summary.groups["clean"].n == 1 and summary.groups["split:test"].n == 2
    assert summary.headline.hygiene is not None and summary.headline.hygiene.far_missed == 1


def _session(verdicts: dict[int, str]) -> SessionData:
    return SessionData.model_validate({
        "session_id": "s", "claims": [], "references": {},
        "verifications": {(n, 3): DbVerification(claim_number=n, ref=3, verdict=v)
                          for n, v in verdicts.items()}})


def test_merged_gold_row_is_scored_on_its_most_severe_copy() -> None:
    sentence = "Drug X reduced IL-6 and TNF in mice."
    row = GoldRow.model_validate({
        "id": pair_id(sentence, 3), "session_id": "s", "claim_number": 1,
        "sentence": sentence, "claim": sentence, "ref": 3, "gold_label": "partially_supported",
        "gold_binary": "problem", "gold_source": "review_D"})
    key = (" ".join(sentence.lower().split()), 3)
    found = find_verification(row, _session({1: "supported", 2: "partially_supported"}),
                              {key: [1, 2]})
    assert found is not None and found.verdict == "partially_supported"
    same = find_verification(row, _session({1: "supported", 2: "supported"}), {key: [2, 1]})
    assert same is not None and same.claim_number == 1  # ties: the row's own claim
    assert find_verification(row, _session({}), {key: [1]}) is None


def test_ablation_delta_table_per_split() -> None:
    base = [rec("partially_supported", "supported", id="a", split="dev"),
            rec("supported", "supported", id="b", split="dev"),
            rec("supported", "partially_supported", id="c", split="test")]
    variant = [base[0].model_copy(update={"verdict": "partially_supported"}),
               base[1], base[2].model_copy(update={"needs_call": True})]
    results = {"all-on": metrics_by_split(base), "no3": metrics_by_split(variant)}
    assert results["all-on"]["dev"].missed_partial == "1/1"
    assert set(results["no3"]) == {"dev", "test", "all"}
    text = "\n".join(delta_table(results, "all-on"))
    assert "split=dev" in text and "split=test" in text
    assert "0/1 (-1)" in text and "1 (+1)" in text
