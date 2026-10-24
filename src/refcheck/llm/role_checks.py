"""Which preflighted roles failed, and which of those stop a run (V5.8: the verifier)."""

from collections.abc import Mapping

from refcheck.llm.errors import LLMError
from refcheck.llm.roles import RoleStatus
from refcheck.llm.types import HARD_ROLES

__all__ = ["PreflightError", "failed_roles", "hard_failed_roles"]


class PreflightError(LLMError):
    """One or more required roles have no working model."""

    def __init__(self, message: str) -> None:
        super().__init__(message, "unavailable")


def failed_roles(statuses: Mapping[str, RoleStatus]) -> list[str]:
    """Roles that have candidates but no working model.

    Roles disabled on purpose (screen switched off, screen/embedding under
    anthropic_only) have no candidates and are not failures.
    """
    return [role for role, status in statuses.items()
            if not status.available and status.candidates]


def hard_failed_roles(statuses: Mapping[str, RoleStatus]) -> list[str]:
    """Failed roles a run cannot do without (HARD_ROLES: the verifier)."""
    return [role for role in failed_roles(statuses) if role in HARD_ROLES]
