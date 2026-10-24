"""ModelSpec: everything the LLM layer needs to know about one model."""

from pydantic import BaseModel, ConfigDict, Field

from refcheck.llm.types import ModelKind, Role

# Effort levels in increasing order; used to pick the closest supported level.
EFFORT_ORDER: tuple[str, ...] = ("none", "minimal", "low", "medium", "high", "xhigh", "max")


class ModelSpec(BaseModel):
    """Static description of a model (prices are USD per 1M tokens)."""

    model_config = ConfigDict(frozen=True)

    id: str
    litellm_id: str
    provider: str
    env_keys: list[str] = Field(default_factory=list)
    roles: list[Role] = Field(default_factory=list)
    kind: ModelKind = "chat"
    display_name: str = ""
    input_cost_per_m: float = 0.0
    output_cost_per_m: float = 0.0
    # None -> billed like normal input (e.g. Decisions API: no cache discount).
    cached_input_cost_per_m: float | None = None
    cache_write_cost_per_m: float | None = None
    max_context: int = 128_000
    max_output_tokens: int = 4096
    supports_temperature: bool = False
    supports_json_schema: bool = True
    # Default effort sent for this model; None = never send reasoning_effort.
    reasoning_effort: str | None = None
    # Efforts the API accepts; empty = reasoning_effort unsupported.
    allowed_efforts: list[str] = Field(default_factory=list)
    dimensions: int | None = None
    timeout_s: float | None = None
    # Optional entries stay in the registry but are never role defaults.
    optional: bool = False

    @property
    def family(self) -> str:
        """Model family for 'independent confirmation' checks (= provider)."""
        return self.provider

    @property
    def label(self) -> str:
        """Human-readable name used in UI traces."""
        return self.display_name or self.id

    def effective_effort(self, requested: str | None) -> str | None:
        """Map a requested effort onto what this model accepts.

        Claude treats "none" as the server default (medium/high), and
        gpt-6.1-sol rejects "none" outright, so "none" degrades to the
        lowest supported level instead of being sent.
        """
        if not self.allowed_efforts:
            return None
        wanted = requested or self.reasoning_effort
        if wanted is None:
            return None
        if wanted in self.allowed_efforts:
            return wanted
        rank = EFFORT_ORDER.index(wanted) if wanted in EFFORT_ORDER else 0
        for level in EFFORT_ORDER[rank:]:
            if level in self.allowed_efforts:
                return level
        return self.allowed_efforts[-1]

    def with_effort(self, requested: str | None) -> "ModelSpec":
        """Copy of this spec with the effective effort for a role applied."""
        effort = self.effective_effort(requested)
        if effort == self.reasoning_effort:
            return self
        return self.model_copy(update={"reasoning_effort": effort})
