"""Probe every role's resolved model (incl. the Decisions API) with tiny calls.

Uses the V5 model registry + ``refcheck.llm.health.preflight``: each role
(screen, verifier, judge, confirm, utility, embedding) gets one tiny real
call; failing models fall back to the next candidate exactly like the app.

Run:
    python scripts/test_llm_connectivity.py                 # all roles
    python scripts/test_llm_connectivity.py --roles judge,confirm
    python scripts/test_llm_connectivity.py --all-models    # every registry model with a key
    python scripts/test_llm_connectivity.py --reset-keys    # forget 'exhausted key' markers
    python scripts/test_llm_connectivity.py --json out.json

Exit code 1 when a role has no working model (a disabled screen is fine).
Key values are never printed — only env var names.
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from refcheck.llm import keys  # noqa: E402
from refcheck.llm.cost_tracker import CostTracker  # noqa: E402
from refcheck.llm.errors import LLMError, short_error  # noqa: E402
from refcheck.llm.health import failed_roles, preflight, probe_model  # noqa: E402
from refcheck.llm.model_registry import REGISTRY  # noqa: E402
from refcheck.llm.roles import privacy_profile, role_effort  # noqa: E402
from refcheck.llm.types import ALL_ROLES, Role  # noqa: E402


def _out(line: str = "") -> None:
    sys.stdout.write(line + "\n")


def _parse_roles(raw: str | None) -> list[Role]:
    if not raw:
        return list(ALL_ROLES)
    wanted = [r.strip() for r in raw.split(",") if r.strip()]
    return [r for r in ALL_ROLES if r in wanted]


async def _probe_all_models(tracker: CostTracker) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for spec in REGISTRY.values():
        if not keys.has_key(spec.provider):
            rows.append({"model": spec.id, "status": "SKIP (no key)"})
            continue
        role: Role = spec.roles[0] if spec.roles else "utility"
        tuned = spec.with_effort(role_effort(role))
        start = time.perf_counter()
        try:
            await probe_model(tuned, role, tracker, timeout=60.0)
            rows.append({"model": spec.id, "status": "OK",
                         "latency_ms": int((time.perf_counter() - start) * 1000)})
        except (LLMError, TimeoutError) as exc:
            rows.append({"model": spec.id, "status": "FAIL", "error": short_error(exc, 160)})
    return rows


async def _main(args: argparse.Namespace) -> int:
    if args.reset_keys:
        keys.reset_keys(clear_persisted=True)
    tracker = CostTracker(max_cost=1.0)
    _out("=" * 72)
    _out(f"RefCheck LLM connectivity - privacy profile: {privacy_profile()}")
    for provider in sorted(keys.PROVIDER_ENV_KEYS):
        _out(f"  {provider:9s} keys={keys.key_count(provider)} "
             f"in_use={keys.current_slot(provider) or '-'}")
    _out("=" * 72)
    statuses = await preflight(_parse_roles(args.roles), force=True, cost_tracker=tracker)
    for role, st in statuses.items():
        mark = "OK " if st.available else ("-- " if not st.candidates else "XX ")
        model = f"{st.model_id} (effort={st.reasoning_effort})" if st.model_id else "-"
        latency = f"{st.latency_ms}ms" if st.latency_ms is not None else ""
        _out(f"[{mark}] {role:9s} -> {model:40s} {latency}")
        if st.reason:
            _out(f"         note: {st.reason}")
    report: dict[str, object] = {"roles": {r: s.model_dump() for r, s in statuses.items()}}
    if args.all_models:
        _out("-" * 72)
        rows = await _probe_all_models(tracker)
        for row in rows:
            _out(f"  {row['model']!s:26s} {row['status']!s:14s} {row.get('error', '')!s}")
        report["models"] = rows
    summary = tracker.summary()
    _out("-" * 72)
    _out(f"Spend: ${summary.total_usd:.5f} over {summary.total_calls} calls")
    report["cost"] = summary.model_dump()
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        _out(f"Report written to {args.json}")
    failed = failed_roles(statuses)
    if failed:
        _out(f"CRITICAL: no working model for: {', '.join(failed)}")
        return 1
    return 0


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--roles", help="comma list of roles (default: all)")
    parser.add_argument("--all-models", action="store_true", help="probe every registry model")
    parser.add_argument("--reset-keys", action="store_true", help="clear exhausted-key markers")
    parser.add_argument("--json", help="write a JSON report to this path")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("LiteLLM").setLevel(logging.WARNING)
    sys.exit(asyncio.run(_main(args)))


if __name__ == "__main__":
    main()
