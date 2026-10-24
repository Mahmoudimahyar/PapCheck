"""Turn a model name (registry id or litellm id) into a ModelSpec.

Unknown names (e.g. an eval ``--model`` override) get an ad-hoc spec priced
from litellm's cost map when available, so cost tracking still works.
"""

import logging

from refcheck.llm.keys import PROVIDER_ENV_KEYS
from refcheck.llm.model_registry import get_spec
from refcheck.llm.model_spec import ModelSpec
from refcheck.llm.types import ModelKind

logger = logging.getLogger(__name__)

_PREFIX_GUESS: tuple[tuple[str, str], ...] = (
    ("claude", "anthropic"), ("gpt", "openai"), ("text-embedding", "openai"),
    ("o1", "openai"), ("o3", "openai"), ("o4", "openai"),
    ("gemini", "gemini"), ("grok", "xai"),
)


def _guess_provider(name: str) -> tuple[str, str]:
    """Return (provider, litellm_id) for a bare or prefixed model name."""
    if "/" in name:
        provider = name.split("/", 1)[0]
        return ("nvidia" if provider == "nvidia_nim" else provider), name
    for prefix, provider in _PREFIX_GUESS:
        if name.startswith(prefix):
            return provider, f"{provider}/{name}"
    return "openai", f"openai/{name}"


def _litellm_prices(name: str, litellm_id: str) -> dict[str, float]:
    """Best-effort price lookup in litellm's bundled cost map."""
    import litellm  # local import: only needed for unknown models

    bare = litellm_id.split("/", 1)[-1]
    entry = litellm.model_cost.get(litellm_id) or litellm.model_cost.get(bare) \
        or litellm.model_cost.get(name)
    if not isinstance(entry, dict):
        return {}
    prices: dict[str, float] = {}
    for src, dst in (("input_cost_per_token", "input_cost_per_m"),
                     ("output_cost_per_token", "output_cost_per_m"),
                     ("cache_read_input_token_cost", "cached_input_cost_per_m")):
        value = entry.get(src)
        if isinstance(value, (int, float)):
            prices[dst] = float(value) * 1_000_000
    return prices


def spec_for(name: str, kind: ModelKind = "chat") -> ModelSpec:
    """Registry spec for ``name`` or an ad-hoc spec for unknown models."""
    spec = get_spec(name, kind) or get_spec(name)
    if spec is not None:
        return spec
    provider, litellm_id = _guess_provider(name)
    logger.warning("Model %s is not in the registry; using an ad-hoc spec", name)
    efforts = ["none", "low", "medium", "high"] if provider == "openai" else (
        ["low", "medium", "high"] if provider in ("anthropic", "gemini") else [])
    return ModelSpec.model_validate({
        "id": name, "litellm_id": litellm_id, "provider": provider, "kind": kind,
        "env_keys": PROVIDER_ENV_KEYS.get(provider, []), "display_name": name,
        "allowed_efforts": efforts if kind == "chat" else [],
        **_litellm_prices(name, litellm_id),
    })
