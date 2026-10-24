"""Settings of the optional open-access fetch (V5.8, G3). OFF unless the user turns it on.

A download needs the user's consent, so nothing is fetched unless
REFCHECK_OA_FETCH=on. Unpaywall needs a contact e-mail: it is read from
REFCHECK_CONTACT_EMAIL only (never hard-coded, never sent to any other host);
without it Unpaywall is skipped and only Europe PMC / PMC are asked. Under pytest
a live fetch never runs (a test injects a mocked HTTP client instead).
"""

import os
import re

from pydantic import BaseModel

_ON = frozenset({"on", "1", "true", "yes"})
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DEFAULT_MAX_MB = 50
_DEFAULT_MAX_FETCHES = 25
_DEFAULT_TIMEOUT_S = 30.0


class OaSettings(BaseModel):
    """What the open-access fetch may do in this run."""

    enabled: bool = False
    contact_email: str = ""  # "" -> Unpaywall is skipped
    max_bytes: int = _DEFAULT_MAX_MB * 1024 * 1024
    max_fetches: int = _DEFAULT_MAX_FETCHES  # references per run
    timeout_s: float = _DEFAULT_TIMEOUT_S


def oa_fetch_enabled() -> bool:
    """REFCHECK_OA_FETCH=on (default off)."""
    return os.getenv("REFCHECK_OA_FETCH", "off").strip().lower() in _ON


def under_pytest() -> bool:
    """A test run: live downloads are refused (tests pass a mocked client)."""
    return "PYTEST_CURRENT_TEST" in os.environ


def load_oa_settings() -> OaSettings:
    """Settings from the environment (module doc)."""
    email = os.getenv("REFCHECK_CONTACT_EMAIL", "").strip()
    return OaSettings(
        enabled=oa_fetch_enabled(),
        contact_email=email if _EMAIL_RE.match(email) else "",
        max_bytes=_positive_int("REFCHECK_OA_MAX_MB", _DEFAULT_MAX_MB) * 1024 * 1024,
        max_fetches=_positive_int("REFCHECK_OA_MAX_FETCHES", _DEFAULT_MAX_FETCHES),
    )


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else default
