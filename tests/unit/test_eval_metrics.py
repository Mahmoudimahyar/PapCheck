"""Unit tests for the eval label mapping, clearance rule and summary metrics."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "eval"))

from eval_clearance import auto_cleared, cleared, predicted_label, verifier_cosigns  # noqa: E402
from eval_metrics import compute_block, summarize  # noqa: E402
from eval_models import ItemRecord, LayerRecord, RunMeta, ScreenRecord  # noqa: E402


def rec(gold: str = "supported", verdict: str = "supported", mode: str = "cascade",
        s: float | None = 0.99, gates: tuple[str, ...] = (), cv: str | None = None,
        decided_by: str = "verifier", path: tuple[str, ...] = ("screen", "verifier"),
        l2: str | None = "supported", l2_quotes: tuple[str, ...] = ("supports",),
        dataset: str = "citation_integrity", synthetic: bool = False, cost: float = 0.001,
        latency: int = 1000, fine: str = "", item_id: str = "",
        consensus: str = "") -> ItemRecord:
    layers = [LayerRecord(layer="verifier", role="verifier", verdict=l2,
                          quote_roles=list(l2_quotes) if l2 else [])] if l2 is not None \
        or "verifier" in path else []
    return ItemRecord(
        id=item_id or f"{gold}-{verdict}-{s}-{id(gates)}", dataset=dataset, synthetic=synthetic,
        gold_label=gold, gold_binary="ok" if gold == "supported" else "problem",
        fine_label=fine, mode=mode,  # type: ignore[arg-type]
        screen=ScreenRecord(probs={}, s=s, model="gpt-6-luna-decisions") if s is not None
        else None, gate_failures=list(gates), layers=layers, verdict=verdict,
        cannot_verify_reason=cv, decided_by=decided_by, layer_path=list(path),
        consensus_type=consensus, cost_usd=cost, latency_ms=latency)


def meta(t_accept: float = 0.97, mode: str = "cascade") -> RunMeta:
    return RunMeta(run_name="t", mode=mode, dataset="smoke", split="dev",  # type: ignore[arg-type]
                   dataset_path="x", n_items=0, source="auto", use_embeddings=False,
                   concurrency=1, started_at="now",
                   thresholds={"t_accept": t_accept, "enabled": True})


@pytest.mark.parametrize(("verdict", "cv", "expected"), [
    ("supported", None, "supported"),
    ("contradicted", None, "contradicted"),
    ("insufficient_evidence", None, "not_supported"),
    ("cannot_verify", "insufficient_in_source", "not_supported"),
    ("cannot_verify", "abstract_insufficient", "not_supported"),
    ("cannot_verify", "llm_error", None),
    ("error", None, None),
    ("n/a", None, None),
])
def test_predicted_label_mapping(verdict: str, cv: str | None, expected: str | None) -> None:
    assert predicted_label(rec(verdict=verdict, cv=cv)) == expected


def test_clearance_needs_gates_threshold_and_cosign() -> None:
    good = rec(s=0.98)
    assert cleared(good, 0.97, cosign=True)
    assert not cleared(good, 0.99, cosign=True)  # below threshold
    assert not cleared(rec(s=0.99, gates=("numeric_claim",)), 0.5, cosign=False)
    assert not cleared(rec(s=None), 0.5, cosign=False)  # no screen
    no_quote = rec(s=0.99, l2_quotes=())
    assert cleared(no_quote, 0.97, cosign=False)
    assert not cleared(no_quote, 0.97, cosign=True)
    assert not cleared(rec(s=0.99, l2="partially_supported"), 0.97, cosign=True)


def test_cosign_uses_the_expanded_rerun_when_present() -> None:
    record = rec(l2="insufficient_evidence", l2_quotes=())
    record.layers.append(LayerRecord(layer="verifier_expanded", role="verifier",
                                     verdict="supported", quote_roles=["supports"]))
    assert verifier_cosigns(record)


def test_auto_cleared_per_mode() -> None:
    assert auto_cleared(rec(decided_by="screen"), None) is True
    assert auto_cleared(rec(decided_by="judge"), 0.5) is False
    assert auto_cleared(rec(mode="screen", s=0.98, l2=None, path=("screen",)), 0.97) is True
    assert auto_cleared(rec(mode="verifier", s=0.98, l2_quotes=()), 0.97) is False
    assert auto_cleared(rec(mode="judge"), 0.97) is None


def test_block_classification_and_binary_metrics() -> None:
    records = [
        rec("supported", "supported"), rec("supported", "partially_supported"),
        rec("contradicted", "contradicted", decided_by="judge"),
        rec("not_supported", "cannot_verify", cv="abstract_insufficient", decided_by="judge"),
        rec("not_relevant", "cannot_verify", cv="llm_error", decided_by="none"),
    ]
    block = compute_block(records, 0.97)
    assert (block.n, block.n_scored, block.n_errors) == (5, 4, 1)
    assert block.accuracy_6way == pytest.approx(3 / 4)
    # gold problem: contradicted, not_supported (scored); predicted problem: partial too
    assert (block.problem.tp, block.problem.fp, block.problem.fn) == (2, 1, 0)
    assert block.confusion["not_supported"] == {"cannot_verify:abstract_insufficient": 1}
    assert block.decided_by == {"verifier": 2, "judge": 2, "none": 1}


def test_block_auto_clear_cost_latency_and_routing_rates() -> None:
    records = [
        rec(decided_by="screen", cost=0.001, latency=100, consensus="screen_clear"),
        rec("partially_supported", decided_by="screen", cost=0.001, latency=200,
            consensus="screen_clear"),
        # V5.1: an unusual positive goes to the judge ...
        rec(decided_by="judge", path=("screen", "verifier", "judge"), consensus="judge",
            cost=0.02, latency=9000),
        # ... while a negative gets the blind cross-check (here: disputed)
        rec("contradicted", "contradicted", path=("screen", "verifier", "confirm"),
            consensus="disputed", cost=0.002, latency=300),
    ]
    block = compute_block(records, 0.97)
    assert block.auto_clear is not None
    assert (block.auto_clear.n_cleared, block.auto_clear.problems) == (2, 1)
    assert block.auto_clear.coverage == pytest.approx(0.5)
    assert block.auto_clear.problem_rate == pytest.approx(0.5)
    assert block.auto_clear.cp_upper_95 > 0.5
    assert block.escalation_rate == pytest.approx(0.25)
    assert block.cross_check_rate == pytest.approx(0.25)
    assert block.consensus == {"screen_clear": 2, "judge": 1, "disputed": 1}
    assert block.cost_per_1k_pairs == pytest.approx(1000 * 0.024 / 4)
    assert block.latency_p50_ms == pytest.approx(250.0)


def test_screen_mode_scores_clearance_only() -> None:
    records = [
        rec(mode="screen", verdict="n/a", s=0.99, l2=None, path=("screen",)),
        rec("contradicted", mode="screen", verdict="n/a", s=0.2, l2=None, path=("screen",)),
        rec("contradicted", mode="screen", verdict="n/a", s=0.99, l2=None, path=("screen",)),
    ]
    block = compute_block(records, 0.97)
    assert block.accuracy_6way is None
    assert block.n_scored == 3
    assert block.auto_clear is not None and block.auto_clear.n_cleared == 2
    assert (block.problem.tp, block.problem.fn, block.problem.tn) == (1, 1, 1)


def test_summary_excludes_synthetic_from_headline() -> None:
    records = [
        rec(dataset="scifact"), rec("not_relevant", "not_relevant", dataset="scifact",
                                    synthetic=True),
        rec("contradicted", "supported", dataset="citation_integrity", fine="CONTRADICT"),
    ]
    summary = summarize(records, meta())
    assert summary.headline.n == 2
    assert summary.synthetic is not None and summary.synthetic.n == 1
    assert set(summary.by_dataset) == {"scifact", "citation_integrity"}
    assert summary.by_dataset["citation_integrity"].accuracy_6way == 0.0
    assert summary.headline.flagged_by_fine_label == {"CONTRADICT": "0/1"}
