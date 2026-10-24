"""One tiny real call against a model (preflight / ``/api/health?deep=true``)."""

from pydantic import BaseModel

from refcheck.llm.client import call_llm
from refcheck.llm.cost_tracker import CostTracker
from refcheck.llm.decision_models import DecisionQuestion
from refcheck.llm.decisions import decide
from refcheck.llm.embeddings import embed
from refcheck.llm.errors import LLMError
from refcheck.llm.model_spec import ModelSpec
from refcheck.llm.templates import render_template
from refcheck.llm.types import Role

__all__ = ["PreflightReply", "probe_model"]

_PROBE_INPUT = "The sky is blue."


class PreflightReply(BaseModel):
    """Expected chat probe reply."""

    ok: bool


async def probe_model(
    spec: ModelSpec, role: Role, tracker: CostTracker | None = None, timeout: float = 45.0,
) -> None:
    """One tiny real call against ``spec``; raises LLMError (or TimeoutError)."""
    if spec.kind == "decision":
        question = DecisionQuestion(name="probe", instructions=render_template(
            "llm_preflight_decision", {}).strip())
        result = await decide(_PROBE_INPUT, [question], role=role, cost_tracker=tracker,
                              task="preflight", model=spec.id, timeout=timeout)
        if result.probability("probe") is None:
            raise LLMError("decisions probe was refused", "refusal", spec.id)
    elif spec.kind == "embedding":
        vectors = await embed(["preflight check"], model=spec.id, cost_tracker=tracker,
                              task="preflight", use_cache=False)
        if not vectors or not vectors[0]:
            raise LLMError("empty embedding", "invalid_output", spec.id)
    else:
        reply = await call_llm("llm_preflight", {}, PreflightReply, model=spec.id, role=role,
                               max_retries=0, use_cache=False, cost_tracker=tracker,
                               task="preflight", max_output_tokens=1024, timeout=timeout)
        if not reply.ok:
            raise LLMError("probe replied ok=false", "invalid_output", spec.id)
