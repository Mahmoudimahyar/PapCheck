"""Run configuration and provenance of an eval run (run_eval.py flags, summary.json meta).

Re-exported by eval_models, so ``from eval_models import EvalConfig, RunMeta`` keeps working.
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

# "recorded": verdicts read back from an app run (score_recorded.py), no LLM calls.
Mode = Literal["screen", "verifier", "judge", "confirm", "cascade", "recorded"]
SourceMode = Literal["auto", "full", "retrieved", "abstract"]
EVAL_DIR = Path.home() / ".refcheck" / "eval"
RESULTS_DIR = EVAL_DIR / "results"


class EvalConfig(BaseModel):
    """One eval run (CLI flags of run_eval.py)."""

    dataset: str = "smoke"
    split: str = "dev"
    mode: Mode = "cascade"
    models: dict[str, str] = Field(default_factory=dict)  # role -> model id override
    efforts: dict[str, str] = Field(default_factory=dict)  # role -> reasoning effort
    limit: int = 0
    concurrency: int = 8
    run_name: str = ""
    source: SourceMode = "auto"
    use_embeddings: bool = True
    with_screen: bool = True  # verifier mode: also run the screen (needed for calibration)
    skip_synthetic: bool = False
    t_accept: float | None = None
    max_cost: float = 5.0
    reuse_cache: bool = False
    results_dir: Path = RESULTS_DIR
    dry_run: bool = False  # canned LLM answers, no screen / embeddings / API calls
    adjudicate: str | None = None  # "on" / "off" sets REFCHECK_ADJUDICATE; None = env
    cocited_union: str | None = None  # "on" / "off" sets REFCHECK_COCITED_UNION; None = env
    strict_clearance: str | None = None  # "on"/"off" sets REFCHECK_STRICT_CLEARANCE; None = env
    session: str = ""  # DB session for co-cited sources ("" = each gold row's session_id)
    # Reuse the screen answers recorded per item by this earlier run (no Decisions call).
    screen_from: str = ""
    # Cache-only: no call is ever sent (keys blanked); a pair whose calls miss the cache
    # is marked needs_call and scored with its verdict from fallback_from (eval_cache).
    offline: bool = False
    fallback_from: str = ""  # reference run for needs_call pairs ("" = screen_from)
    # --offline: chat calls of these roles may be sent (eval_live); only the keys of their
    # providers survive the blanking (live_keys: those env var names, [] = all of them).
    live_roles: list[str] = Field(default_factory=list)
    live_keys: list[str] = Field(default_factory=list)
    live_check: bool = False  # --live-roles dry check: record the live calls, send nothing
    # --offline: "bm25" turns an embedding cache miss into BM25-only retrieval (as the app
    # does without OpenAI credits, V5.8 G1) instead of a needs_call pair.
    embedding_miss: str = "miss"


class RunMeta(BaseModel):
    """Provenance of a run (written to summary.json; read by calibrate_screen.py)."""

    run_name: str
    mode: Mode
    dataset: str
    split: str
    dataset_path: str
    n_items: int
    source: SourceMode
    use_embeddings: bool
    concurrency: int
    started_at: str
    finished_at: str = ""
    roles: dict[str, str | None] = Field(default_factory=dict)  # role -> resolved model id
    efforts: dict[str, str | None] = Field(default_factory=dict)
    thresholds: dict[str, float | bool | str] = Field(default_factory=dict)
    screen_template_hash: str = ""
    prompt_hashes: dict[str, str] = Field(default_factory=dict)
    retrieval_versions: list[str] = Field(default_factory=list)
    reuse_cache: bool = False
    dry_run: bool = False
    adjudicate: bool = False  # REFCHECK_ADJUDICATE at run time (cascade mode)
    cocited_union: bool = False  # REFCHECK_COCITED_UNION at run time (with the adjudicator)
    strict_clearance: bool = False  # REFCHECK_STRICT_CLEARANCE at run time (V5.6 strict)
    max_cost: float = 0.0
    total_cost_usd: float = 0.0
    cost_by_role: dict[str, float] = Field(default_factory=dict)
    cost_by_task: dict[str, float] = Field(default_factory=dict)
    screen_from: str = ""  # run whose recorded screen answers were reused
    offline: bool = False  # cache-only run (no API call possible)
    fallback_from: str = ""  # run that scored the needs_call pairs (offline)
    live_roles: list[str] = Field(default_factory=list)  # offline roles that could call
    live_check: bool = False  # --live-check: those calls were recorded, not sent
    v57_disable: str = ""  # REFCHECK_V57_DISABLE at run time (proposal ablation)
    v57_enable: str = ""  # REFCHECK_V57_ENABLE: opted-in experimental V5.8 proposals
    embedding_miss: str = "miss"  # --embedding-miss (offline: "bm25" = BM25-only on a miss)
