"""LLM-layer exceptions, provider error classification and secret redaction."""

import re

import litellm

from refcheck.llm.keys import known_secrets
from refcheck.llm.types import HARD_FAILURES, ErrorKind


class LLMError(Exception):
    """Base class for every failure raised by refcheck.llm."""

    def __init__(self, message: str, kind: ErrorKind = "other",
                 model_id: str | None = None) -> None:
        super().__init__(message)
        self.kind: ErrorKind = kind
        self.model_id = model_id

    @property
    def is_hard(self) -> bool:
        """Hard failures (billing/auth/404/no key) disable the model."""
        return self.kind in HARD_FAILURES


class LLMCallError(LLMError):
    """The provider call failed (after retries / key rotation)."""


class LLMResponseInvalidError(LLMError):
    """LLM returned unparseable or schema-invalid output."""

    def __init__(self, message: str, kind: ErrorKind = "invalid_output",
                 model_id: str | None = None) -> None:
        super().__init__(message, kind, model_id)


class LLMRefusalError(LLMResponseInvalidError):
    """The model refused to answer (content filter / refusal field)."""

    def __init__(self, message: str, model_id: str | None = None) -> None:
        super().__init__(message, "refusal", model_id)


class NoModelAvailableError(LLMError):
    """No model with a usable key is left for a role."""

    def __init__(self, message: str, model_id: str | None = None) -> None:
        super().__init__(message, "unavailable", model_id)


_BILLING_MARKERS = (
    "credit balance", "billing", "insufficient_quota", "exceeded your current quota",
    "payment required", "spending limit", "insufficient credit", "out of credits",
    "purchase credits",
)
_KEYLIKE = re.compile(r"\b(sk|sk-ant|sk-proj|xai|nvapi|AIza)[-_A-Za-z0-9*]{6,}")


def classify_error(exc: BaseException) -> ErrorKind:
    """Map a litellm/provider exception onto an ErrorKind."""
    status = getattr(exc, "status_code", None)
    msg = str(exc).lower()
    if isinstance(exc, litellm.exceptions.ContextWindowExceededError):
        return "context_window"
    if status == 402 or any(marker in msg for marker in _BILLING_MARKERS):
        return "billing"
    if isinstance(exc, (litellm.exceptions.AuthenticationError,
                        litellm.exceptions.PermissionDeniedError)) or status in (401, 403):
        return "auth"
    if isinstance(exc, litellm.exceptions.NotFoundError) or status == 404:
        return "not_found"
    if isinstance(exc, litellm.exceptions.RateLimitError) or status == 429:
        return "rate_limit"
    if isinstance(exc, (litellm.exceptions.Timeout, TimeoutError)) or "timed out" in msg:
        return "timeout"
    if isinstance(exc, litellm.exceptions.ContentPolicyViolationError):
        return "content_filter"
    transient_types = (
        litellm.exceptions.APIConnectionError, litellm.exceptions.ServiceUnavailableError,
        litellm.exceptions.InternalServerError, ConnectionError,
    )
    if isinstance(exc, transient_types) or (isinstance(status, int) and status >= 500):
        return "transient"
    if isinstance(exc, litellm.exceptions.BadRequestError) or status == 400:
        return "bad_request"
    return "other"


def is_key_failure(exc: BaseException, kind: ErrorKind) -> bool:
    """Billing or an invalid key (401) condemns the KEY; a 403 is usually about one model.

    Rotating (and persisting the key as exhausted) on a model-level 403 would
    disable the provider's key for every model, so a 403 only benches the model.
    """
    if kind == "billing":
        return True
    if kind != "auth":
        return False
    status = getattr(exc, "status_code", None)
    return isinstance(exc, litellm.exceptions.AuthenticationError) or status == 401


def redact(text: str) -> str:
    """Remove any loaded API key (and key-shaped tokens) from a message."""
    for secret in known_secrets():
        if secret:
            text = text.replace(secret, "<redacted>")
    return _KEYLIKE.sub("<redacted>", text)


def short_error(exc: BaseException, limit: int = 300) -> str:
    """Redacted, truncated one-line description of an exception."""
    first = " ".join(str(exc).split())
    return redact(f"{type(exc).__name__}: {first}")[:limit]
