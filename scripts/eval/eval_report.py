"""Plain-text rendering of eval summaries (logged by the CLIs; no print())."""

from eval_hygiene import hygiene_line
from eval_metrics import MetricBlock, RunSummary
from eval_partial import partial_line
from eval_recorded import offline_line


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{100 * value:.1f}%"


def _num(value: float | None, digits: int = 3) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def block_line(name: str, block: MetricBlock) -> str:
    """One compact line with every headline metric of a block."""
    parts = [
        f"{name}: n={block.n} scored={block.n_scored} errors={block.n_errors}",
        f"acc6={_pct(block.accuracy_6way)} macroF1={_num(block.macro_f1)}",
        f"problem P/R/F1={_num(block.problem.precision)}/{_num(block.problem.recall)}"
        f"/{_num(block.problem.f1)}",
    ]
    clear = block.auto_clear
    if clear is not None:
        parts.append(f"auto-clear {clear.n_cleared} ({_pct(clear.coverage)}) problems "
                     f"{clear.problems} rate={_pct(clear.problem_rate)} "
                     f"CP95<={_pct(clear.cp_upper_95)}")
    if block.escalation_rate is not None:
        parts.append(f"to-judge={_pct(block.escalation_rate)} "
                     f"cross-checked={_pct(block.cross_check_rate)} "
                     f"disputed={block.consensus.get('disputed', 0)}")
    parts.append(f"${_num(block.cost_per_1k_pairs, 2)}/1k pairs "
                 f"p50={_num(block.latency_p50_ms, 0)}ms p90={_num(block.latency_p90_ms, 0)}ms")
    return " | ".join(parts)


def adjudication_line(counts: dict[str, int]) -> str:
    """Element adjudicator: how often it ran and what it changed."""
    return (f"adjudicator: ran {sum(counts.values())}, cleared fully "
            f"{counts.get('cleared', 0)}, partially {counts.get('partial', 0)} "
            f"(held {counts.get('held', 0)}, unchanged {counts.get('unchanged', 0)}, "
            f"errors {counts.get('error', 0)})")


def union_line(counts: dict[str, int]) -> str:
    """Co-cited union check: calls made (skipped = precondition failed, no call)."""
    ran = sum(v for k, v in counts.items() if k != "skipped")
    return (f"union check: ran {ran}, cleared fully {counts.get('cleared', 0)}, partially "
            f"{counts.get('partial', 0)}, held {counts.get('held', 0)} (unchanged "
            f"{counts.get('unchanged', 0)}, errors {counts.get('error', 0)}, skipped by "
            f"precondition {counts.get('skipped', 0)})")


def summary_lines(summary: RunSummary) -> list[str]:
    """Headline, per-dataset and synthetic lines plus run provenance."""
    meta = summary.meta
    lines = [
        f"run {meta.run_name}: mode={meta.mode} data={meta.dataset_path} n={meta.n_items} "
        f"cost=${meta.total_cost_usd:.4f}",
        "roles: " + ", ".join(f"{role}={model}({meta.efforts.get(role) or '-'})"
                              for role, model in sorted(meta.roles.items())),
        f"thresholds: {meta.thresholds}",
        block_line("HEADLINE (non-synthetic)", summary.headline),
    ]
    lines += [block_line(f"  {name}", block) for name, block in summary.by_dataset.items()]
    if summary.synthetic is not None:
        lines.append(block_line("  synthetic (excluded)", summary.synthetic))
    if summary.headline.partial is not None:
        lines.append(partial_line(summary.headline.partial))
    lines.append(hygiene_line("hygiene", summary.headline.hygiene))
    for name, block in summary.groups.items():
        lines += [f"  [{name}] n={block.n} {partial_line(block.partial)}",
                  hygiene_line(f"  [{name}]", block.hygiene)]
    if summary.headline.decided_by:
        lines.append(f"decided_by: {summary.headline.decided_by}")
    if summary.headline.consensus:
        lines.append(f"consensus: {summary.headline.consensus}")
    if meta.adjudicate or summary.headline.adjudication:
        lines.append(adjudication_line(summary.headline.adjudication))
    if meta.cocited_union or summary.headline.cocited_union:
        lines.append(union_line(summary.headline.cocited_union))
    if summary.offline is not None:
        lines.append(offline_line(summary.offline))
    if summary.headline.cached_layer_calls:
        lines.append(f"NOTE: {summary.headline.cached_layer_calls} layer calls came from the "
                     "LLM cache (cost/latency understated)")
    return lines


def pareto_flags(points: list[tuple[float, float, float]]) -> list[bool]:
    """Non-dominated points for (accuracy up, cost down, latency down)."""
    flags: list[bool] = []
    for i, (acc, cost, lat) in enumerate(points):
        dominated = any(
            j != i and a >= acc and c <= cost and la <= lat and (a, c, la) != (acc, cost, lat)
            for j, (a, c, la) in enumerate(points))
        flags.append(not dominated)
    return flags


def table(header: list[str], rows: list[list[str]]) -> list[str]:
    """Left-aligned fixed-width text table."""
    widths = [max(len(str(r[i])) for r in [header, *rows]) for i in range(len(header))]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    return [fmt.format(*header), fmt.format(*("-" * w for w in widths)),
            *(fmt.format(*row) for row in rows)]
