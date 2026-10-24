"""Offline dispute-policy replay (scripts/eval/policy_replay.py) on synthetic records."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "eval"))

from eval_models import ItemRecord, LayerRecord  # noqa: E402
from policy_replay import (  # noqa: E402
    POLICIES,
    confirm_wins,
    gold_agrees,
    keep_verifier,
    replay_cascade,
    replay_paired,
    score,
)

from refcheck.stages.verify_claims.dispute import disputed_verdict  # noqa: E402


def cascade(gold: str, verifier: str, confirm: str | None, recorded: str,
            item_id: str = "x") -> ItemRecord:
    layers = [LayerRecord(layer="verifier", role="verifier", verdict=verifier)]
    path = ["screen", "verifier"]
    if confirm is not None:
        layers.append(LayerRecord(layer="confirm", role="confirm", verdict=confirm))
        path.append("confirm")
    return ItemRecord(id=item_id, dataset="citation_integrity", gold_label=gold,
                      gold_binary="ok" if gold == "supported" else "problem", mode="cascade",
                      layers=layers, verdict=recorded, layer_path=path)


def verifier_run(item_id: str, gold: str, verdict: str) -> ItemRecord:
    return ItemRecord(id=item_id, dataset="citation_integrity", gold_label=gold,
                      gold_binary="ok" if gold == "supported" else "problem", mode="verifier",
                      layers=[LayerRecord(layer="verifier", role="verifier", verdict=verdict)],
                      verdict=verdict, layer_path=["verifier"])


def test_production_policy_is_the_shipped_rule() -> None:
    assert disputed_verdict in POLICIES.values()


def test_dispute_replayed_under_each_policy() -> None:
    rec = cascade("partially_supported", "not_supported", "supported", "not_supported")
    assert replay_cascade(rec, keep_verifier) == "not_supported"  # the old, harsher rule
    assert replay_cascade(rec, disputed_verdict) == "partially_supported"
    assert replay_cascade(rec, confirm_wins) == "supported"


def test_agreement_positive_and_unchecked_records_keep_their_verdict() -> None:
    confirmed = cascade("not_supported", "not_supported", "not_supported", "not_supported")
    positive = cascade("supported", "supported", None, "supported")
    abstract = cascade("not_supported", "not_supported", "insufficient_evidence",
                       "cannot_verify")
    abstract.cannot_verify_reason = "abstract_insufficient"
    for rec in (confirmed, positive, abstract):
        assert replay_cascade(rec, disputed_verdict) == replay_cascade(rec, keep_verifier)


def test_paired_runs_stand_in_for_the_cross_check() -> None:
    v = verifier_run("a", "partially_supported", "not_supported")
    c = verifier_run("a", "partially_supported", "partially_supported")
    assert replay_paired(v, c, keep_verifier) == "not_supported"
    assert replay_paired(v, c, disputed_verdict) == "partially_supported"
    assert replay_paired(v, None, disputed_verdict) == "not_supported"


def test_score_counts_partial_as_a_problem() -> None:
    scores = score(["partially_supported", "supported", "not_supported"],
                   ["partially_supported", "supported", None])
    assert scores.n == 2 and scores.accuracy_6way == 1.0
    assert (scores.problem.tp, scores.problem.tn, scores.problem.fp) == (1, 1, 0)


def test_gold_agreement_rules() -> None:
    assert gold_agrees("partially_supported", "partially_supported")
    assert gold_agrees("partially_supported_tool_ok", "not_supported")
    assert not gold_agrees("wrong_paper", "not_supported")
    assert not gold_agrees("supported", "partially_supported")
