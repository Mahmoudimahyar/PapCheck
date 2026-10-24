"""LLM cache scopes for run_eval.py: a throw-away cache (honest cost), the app's cache
(--reuse-cache), or cache-only (--offline).

--offline never sends a request: every API key env var is blanked (the run refuses to
start if any key is still visible), chat completions, embeddings and the Decisions screen
are replaced by stand-ins that record the miss (role, model, estimated tokens and cost)
on the current pair and raise a soft LLMCallError (kind "other": no model is benched, the
pipeline treats it like a failed call). Role resolution sees every provider as keyed, so
it resolves the same models (and cache keys) a live run would. run_eval marks a pair with
misses needs_call and scores it from the --fallback-from run (eval_recorded). With
--live-roles (eval_live) the kept key env vars survive the blanking and its chat stand-in
replaces cache_only_complete. --embedding-miss bm25: an uncached embedding is not a miss;
it fails softly and retrieval falls back to BM25 only (the app without OpenAI, V5.8 G1).
"""

import os
import tempfile
from collections.abc import Callable, Collection, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import NoReturn
from unittest.mock import patch

from eval_models import EvalConfig, MissedCall

from refcheck.llm import embeddings, keys, structured
from refcheck.llm.cache import close_caches
from refcheck.llm.errors import LLMCallError
from refcheck.llm.model_spec import ModelSpec
from refcheck.llm.usage import TokenUsage, compute_cost
from refcheck.stages.verify_claims import screen

EST_OUTPUT_TOKENS = 500  # mean output of verifier / confirm / adjudicator calls (CI test)
SCREEN_EST_USD = 0.0004  # mean Decisions screen cost per pair (gold and CI runs)
_CHARS_PER_TOKEN = 4
_MISSES: ContextVar[list[MissedCall] | None] = ContextVar("eval_cache_misses", default=None)
SETUP_MISSES: list[MissedCall] = []  # misses outside any pair (e.g. source loading)


@contextmanager
def cache_scope(reuse: bool) -> Iterator[None]:
    """A throw-away LLM/embedding cache dir (honest cost/latency) unless reuse."""
    if reuse:
        yield
        return
    previous = os.environ.get("REFCHECK_CACHE_DIR")
    with tempfile.TemporaryDirectory(prefix="refcheck-eval-",
                                     ignore_cleanup_errors=True) as tmp:
        os.environ["REFCHECK_CACHE_DIR"] = tmp
        try:
            yield
        finally:
            close_caches()
            if previous is None:
                os.environ.pop("REFCHECK_CACHE_DIR", None)
            else:
                os.environ["REFCHECK_CACHE_DIR"] = previous


def key_env_names() -> list[str]:
    """Every env var that can hold an API key (*_API_KEY*, plus the provider key names)."""
    known = {name for names in keys.PROVIDER_ENV_KEYS.values() for name in names}
    return sorted(known | {name for name in os.environ if "_API_KEY" in name.upper()})


def blank_keys(keep: Collection[str] = ()) -> None:
    """Set every API key env var except ``keep`` to "" and forget the loaded key rings."""
    for name in key_env_names():
        if name not in keep:
            os.environ[name] = ""
    keys.reset_keys()


def visible_keys(keep: Collection[str] = ()) -> list[str]:
    """Env var names (never values) outside ``keep`` that still hold a key, plus providers
    with a key ring that no kept env var belongs to."""
    names = [n for n in key_env_names() if n not in keep and os.environ.get(n, "").strip()]
    rings = [f"{p} key ring" for p, envs in keys.PROVIDER_ENV_KEYS.items()
             if keys.key_count(p) and not set(envs) & set(keep)]
    return names + rings


def check_offline(cfg: EvalConfig, screen_needed: bool, keep: Collection[str] = ()) -> None:
    """Blank the keys (all but ``keep``, the --live-roles keys) and refuse (SystemExit) a
    run that could still reach an API through any other key."""
    if cfg.dry_run:
        raise SystemExit("--offline and --dry-run exclude each other")
    if screen_needed and not cfg.screen_from:
        raise SystemExit("--offline needs --screen-from <run>: the screen is not cached")
    blank_keys(keep)
    left = visible_keys(keep)
    if left:
        raise SystemExit(f"refusing to run --offline: API keys still visible ({left})")


def item_misses() -> list[MissedCall]:
    """Start recording the current pair's misses (call at the start of its task)."""
    misses: list[MissedCall] = []
    _MISSES.set(misses)
    return misses


def record_miss(miss: MissedCall) -> None:
    current = _MISSES.get()
    (current if current is not None else SETUP_MISSES).append(miss)


def pair_missed() -> bool:
    """The current pair already missed a call (it is scored from the fallback run)."""
    return bool(_MISSES.get())


def chat_chars(messages: object) -> int:
    """Prompt characters of a chat message list."""
    total = 0
    for message in messages if isinstance(messages, list) else []:
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            total += sum(len(str(b.get("text", ""))) for b in content if isinstance(b, dict))
    return total


def estimate(kind: str, spec: ModelSpec, role: str, chars: int, output: int,
             live: bool = False) -> MissedCall:
    """A call of ``chars`` prompt characters as a MissedCall (estimated tokens and $)."""
    tokens = chars // _CHARS_PER_TOKEN
    cost = compute_cost(spec, TokenUsage(input_tokens=tokens, output_tokens=output))
    return MissedCall.model_validate({"kind": kind, "role": role, "model": spec.id,
                                      "est_input_tokens": tokens, "live": live,
                                      "est_cost_usd": round(cost, 6)})


def _miss(kind: str, spec: ModelSpec, role: str, chars: int, output: int) -> NoReturn:
    record_miss(estimate(kind, spec, role, chars, output))
    raise LLMCallError(f"offline: {spec.id} {kind} call not in the cache (not sent)",
                       "other", spec.id)


async def cache_only_complete(spec: ModelSpec, messages: object, *args: object,
                              **kwargs: object) -> NoReturn:
    """structured.complete stand-in: a chat cache miss (never sent)."""
    _miss("chat", spec, str(kwargs.get("role") or ""), chat_chars(messages), EST_OUTPUT_TOKENS)


async def cache_only_embed(spec: ModelSpec, batch: list[str], *args: object,
                           **kwargs: object) -> NoReturn:
    """embeddings._embed_batch stand-in: an embedding cache miss (never sent)."""
    _miss("embedding", spec, "embedding", sum(len(t) for t in batch), 0)


async def bm25_on_embed_miss(spec: ModelSpec, batch: list[str], *args: object,
                             **kwargs: object) -> NoReturn:
    """--embedding-miss bm25: an uncached embedding fails softly (BM25-only), no miss."""
    raise LLMCallError("offline: embedding not cached (BM25-only retrieval)", "other", spec.id)


async def cache_only_decide(*args: object, **kwargs: object) -> NoReturn:
    """screen.decide stand-in: the screen is never cached (use --screen-from)."""
    record_miss(MissedCall(kind="screen", role="screen", est_cost_usd=SCREEN_EST_USD))
    raise LLMCallError("offline: the screen is not cached (not sent)", "other")


def _keyed(provider: str) -> bool:
    return True


ChatStandIn = Callable[..., object]


@contextmanager
def offline_scope(enabled: bool, chat: ChatStandIn = cache_only_complete,
                  embedding_miss: str = "miss") -> Iterator[None]:
    """Cache-only calls (module doc); a no-op unless ``enabled``. ``chat`` replaces
    structured.complete (eval_live's stand-in sends the --live-roles calls)."""
    embed = bm25_on_embed_miss if embedding_miss == "bm25" else cache_only_embed
    if not enabled:
        yield
        return
    SETUP_MISSES.clear()
    with (patch.object(structured, "complete", chat),
          patch.object(embeddings, "_embed_batch", embed),
          patch.object(screen, "decide", cache_only_decide),
          patch.object(keys, "has_key", _keyed)):
        yield
