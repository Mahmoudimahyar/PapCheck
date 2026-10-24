"""LLM abstraction layer (litellm only through here).

Public API: call_llm / call_llm_raw (chat, structured output), decide
(Decisions API), embed / embed_with_model, resolve_role / role_status,
preflight (refcheck.llm.health; imported lazily to keep this light).
"""

from refcheck.llm.client import LLMCallResult, call_llm, call_llm_raw
from refcheck.llm.cost_tracker import CostLimitExceededError, CostTracker
from refcheck.llm.decisions import (
    DecisionAnswer,
    DecisionError,
    DecisionQuestion,
    DecisionResult,
    decide,
)
from refcheck.llm.embeddings import EmbeddingError, EmbeddingResult, embed, embed_with_model
from refcheck.llm.errors import (
    LLMCallError,
    LLMError,
    LLMRefusalError,
    LLMResponseInvalidError,
    NoModelAvailableError,
)
from refcheck.llm.messages import CACHE_BREAKPOINT
from refcheck.llm.model_spec import ModelSpec
from refcheck.llm.roles import RoleStatus, resolve_role, role_status, same_family, screen_enabled
from refcheck.llm.types import Role
from refcheck.llm.usage import TokenUsage

__all__ = [
    "CACHE_BREAKPOINT", "CostLimitExceededError", "CostTracker", "DecisionAnswer",
    "DecisionError", "DecisionQuestion", "DecisionResult", "EmbeddingError",
    "EmbeddingResult", "LLMCallError", "LLMCallResult", "LLMError", "LLMRefusalError",
    "LLMResponseInvalidError", "ModelSpec", "NoModelAvailableError", "Role", "RoleStatus",
    "TokenUsage", "call_llm", "call_llm_raw", "decide", "embed", "embed_with_model",
    "resolve_role", "role_status", "same_family", "screen_enabled",
]
