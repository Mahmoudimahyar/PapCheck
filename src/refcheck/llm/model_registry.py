"""Model registry (V5): every model we can call, plus role defaults.

Prices/efforts follow MODEL_SELECTION (benchmarked 2026-10-20).
"""

from refcheck.llm.keys import PROVIDER_ENV_KEYS
from refcheck.llm.model_spec import ModelSpec
from refcheck.llm.types import ModelKind, PrivacyProfile, Role

__all__ = [
    "DEGRADED_FALLBACKS", "PROFILE_ROLE_DEFAULTS", "REGISTRY", "ROLE_DEFAULTS", "ROLE_EFFORT",
    "ModelSpec", "get_spec",
]

_OPENAI_EFFORTS = ["none", "low", "medium", "high", "xhigh"]
_SOL_EFFORTS = ["low", "medium", "high", "xhigh"]  # sol rejects "none"
_CLAUDE_EFFORTS = ["low", "medium", "high", "xhigh", "max"]
_GEMINI_EFFORTS = ["low", "medium", "high"]


def _m(provider: str, **fields: object) -> ModelSpec:
    """Build a spec with the provider's env key list filled in."""
    return ModelSpec.model_validate({
        "provider": provider, "env_keys": PROVIDER_ENV_KEYS.get(provider, []), **fields,
    })


_SPECS: list[ModelSpec] = [
    # --- OpenAI -----------------------------------------------------------
    _m("openai", id="gpt-6-luna-decisions", litellm_id="openai/gpt-6-luna",
       kind="decision", roles=["screen"], display_name="Decisions API · gpt-6-luna",
       input_cost_per_m=0.10, max_context=128_000, timeout_s=20),
    _m("openai", id="gpt-6-luna", litellm_id="openai/gpt-6-luna",
       roles=["verifier", "adjudicator", "utility"], display_name="gpt-6-luna",
       input_cost_per_m=0.10, output_cost_per_m=0.50, cached_input_cost_per_m=0.01,
       max_context=922_000, max_output_tokens=4096, reasoning_effort="none",
       allowed_efforts=_OPENAI_EFFORTS, timeout_s=60),
    _m("openai", id="gpt-6.1-sol", litellm_id="openai/gpt-6.1-sol",
       roles=["judge", "confirm"], display_name="gpt-6.1-sol",
       input_cost_per_m=2.0, output_cost_per_m=10.0, cached_input_cost_per_m=0.10,
       max_context=922_000, max_output_tokens=8192, reasoning_effort="low",
       allowed_efforts=_SOL_EFFORTS, timeout_s=120),
    _m("openai", id="gpt-6-astra", litellm_id="openai/gpt-6-astra", optional=True,
       roles=["judge"], display_name="gpt-6-astra",
       input_cost_per_m=10.0, output_cost_per_m=50.0, cached_input_cost_per_m=1.0,
       max_context=922_000, max_output_tokens=8192, reasoning_effort="low",
       allowed_efforts=_SOL_EFFORTS, timeout_s=180),
    _m("openai", id="text-embedding-3-small", litellm_id="openai/text-embedding-3-small",
       kind="embedding", roles=["embedding"], display_name="text-embedding-3-small",
       input_cost_per_m=0.02, max_context=8191, timeout_s=30),
    _m("openai", id="text-embedding-3-large", litellm_id="openai/text-embedding-3-large",
       kind="embedding", roles=["embedding"], display_name="text-embedding-3-large",
       input_cost_per_m=0.13, max_context=8191, dimensions=1024, timeout_s=30),
    # --- Anthropic (cache writes cost 1.25x input, reads 0.05-0.1x) -------
    _m("anthropic", id="claude-haiku-5-5", litellm_id="anthropic/claude-haiku-5-5",
       roles=["verifier", "adjudicator", "utility"], display_name="claude-haiku-5-5",
       input_cost_per_m=0.10, output_cost_per_m=0.50, cached_input_cost_per_m=0.01,
       cache_write_cost_per_m=0.125, max_context=1_000_000, max_output_tokens=4096,
       reasoning_effort="low", allowed_efforts=_CLAUDE_EFFORTS, timeout_s=60),
    _m("anthropic", id="claude-sonnet-5-5", litellm_id="anthropic/claude-sonnet-5-5",
       roles=["judge"], display_name="claude-sonnet-5-5",
       input_cost_per_m=2.0, output_cost_per_m=10.0, cached_input_cost_per_m=0.10,
       cache_write_cost_per_m=2.5, max_context=1_000_000, max_output_tokens=8192,
       reasoning_effort="medium", allowed_efforts=_CLAUDE_EFFORTS, timeout_s=120),
    _m("anthropic", id="claude-opus-5-5", litellm_id="anthropic/claude-opus-5-5",
       roles=["judge", "confirm"], display_name="claude-opus-5-5",
       input_cost_per_m=4.0, output_cost_per_m=20.0, cached_input_cost_per_m=0.20,
       cache_write_cost_per_m=5.0, max_context=1_000_000, max_output_tokens=8192,
       reasoning_effort="low", allowed_efforts=_CLAUDE_EFFORTS, timeout_s=150),
    # --- Optional providers (no credit as of 2026-10-20; never defaults) ---
    _m("gemini", id="gemini-3.8-flash", litellm_id="gemini/gemini-3.8-flash",
       optional=True, roles=["verifier", "judge"], display_name="gemini-3.8-flash",
       input_cost_per_m=0.75, output_cost_per_m=3.75, cached_input_cost_per_m=0.075,
       max_context=1_048_576, max_output_tokens=8192, reasoning_effort="low",
       allowed_efforts=_GEMINI_EFFORTS, timeout_s=90),
    _m("gemini", id="gemini-3.5-flash-lite", litellm_id="gemini/gemini-3.5-flash-lite",
       optional=True, roles=["verifier", "utility"], display_name="gemini-3.5-flash-lite",
       input_cost_per_m=0.30, output_cost_per_m=2.50, cached_input_cost_per_m=0.03,
       max_context=1_048_576, max_output_tokens=4096, reasoning_effort="low",
       allowed_efforts=_GEMINI_EFFORTS, timeout_s=60),
    _m("xai", id="grok-4.3", litellm_id="xai/grok-4.3", optional=True,
       roles=["verifier", "judge"], display_name="grok-4.3",
       input_cost_per_m=1.25, output_cost_per_m=2.50, cached_input_cost_per_m=0.20,
       max_context=1_000_000, max_output_tokens=8192, timeout_s=90),
]

REGISTRY: dict[str, ModelSpec] = {spec.id: spec for spec in _SPECS}

# Ordered fallbacks per role (standard profile); first AVAILABLE model wins.
# Chosen on Citation-Integrity test (scripts/eval, 2026-10-21): claude-haiku-5-5
# was the best verifier (problem F1 0.905, 6-way 47%, $0.74/1k pairs) ahead of
# gpt-6-luna and of every judge (Sonnet 5.5 0.82, Sol 0.77 at $18-27/1k).
# claude-opus-5-5 is excluded: it refused 24% of biomedical pairs (content filter).
# "confirm" must be a different family from the verifier (blind cross-check).
# "adjudicator" answers one narrow question per element of a partial verdict
# (verify_claims/adjudicate.py); a cheap model is enough for that question.
ROLE_DEFAULTS: dict[Role, list[str]] = {
    "screen": ["gpt-6-luna-decisions"],
    "verifier": ["claude-haiku-5-5", "gpt-6-luna"],
    "judge": ["claude-sonnet-5-5", "gpt-6.1-sol"],
    "confirm": ["gpt-6-luna", "gpt-6.1-sol"],
    "adjudicator": ["claude-haiku-5-5", "gpt-6-luna"],
    "utility": ["gpt-6-luna", "claude-haiku-5-5"],
    "embedding": ["text-embedding-3-small", "text-embedding-3-large"],
}

# V5.8 degraded mode: tried only after every normal candidate failed (e.g. the OpenAI
# account has no credits). The confirm fallback is an Anthropic model that is NOT the
# verifier's model (same family -> its confirmations go to review); its spend is capped
# (REFCHECK_DEGRADED_MAX_USD). REFCHECK_DEGRADED_FALLBACKS=off disables this.
DEGRADED_FALLBACKS: dict[Role, list[str]] = {
    "confirm": ["claude-sonnet-5-5", "claude-haiku-5-5"],
}

# Requested effort per role; ModelSpec.effective_effort adapts it per model.
# Sonnet @low matched/beat @medium on the judge benchmark at the same cost.
ROLE_EFFORT: dict[Role, str | None] = {
    "screen": None, "verifier": "low", "judge": "low",
    "confirm": "low", "adjudicator": "low", "utility": "none", "embedding": None,
}

# anthropic_only: nothing leaves Anthropic (screen + embeddings disabled); the
# cross-check is then same-family, so disputed/confirmed flags go to review.
_ANTHROPIC_ONLY: dict[Role, list[str]] = {
    "screen": [], "verifier": ["claude-haiku-5-5"],
    "judge": ["claude-sonnet-5-5"],
    "confirm": ["claude-sonnet-5-5"], "adjudicator": ["claude-haiku-5-5"],
    "utility": ["claude-haiku-5-5"], "embedding": [],
}

PROFILE_ROLE_DEFAULTS: dict[PrivacyProfile, dict[Role, list[str]]] = {
    "standard": ROLE_DEFAULTS, "anthropic_only": _ANTHROPIC_ONLY,
}


def get_spec(name: str, kind: ModelKind | None = None) -> ModelSpec | None:
    """Look up a registry model by id or litellm id (prefers chat models)."""
    spec = REGISTRY.get(name)
    if spec is not None and (kind is None or spec.kind == kind):
        return spec
    matches = [s for s in _SPECS if s.litellm_id == name or s.id == name]
    if kind is not None:
        matches = [s for s in matches if s.kind == kind]
    else:
        matches.sort(key=lambda s: s.kind != "chat")
    return matches[0] if matches else None
