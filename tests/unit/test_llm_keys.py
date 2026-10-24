"""Key rings, persisted exhaustion markers, error classification, redaction."""

import json
import threading
from collections.abc import Iterator
from pathlib import Path

import litellm
import pytest

from refcheck.llm import key_state, keys
from refcheck.llm.errors import classify_error, redact, short_error
from tests.unit.llm_fakes import (
    FAKE_ANTH_BACKUP,
    FAKE_ANTH_PRIMARY,
    FAKE_OPENAI,
    auth_error,
    billing_error,
    isolated_llm_env,
    not_found_error,
    rate_limit_error,
)


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    yield from isolated_llm_env(monkeypatch, tmp_path)


class TestKeyRing:
    def test_primary_key_first(self) -> None:
        assert keys.get_key("anthropic") == FAKE_ANTH_PRIMARY
        assert keys.current_slot("anthropic") == "ANTHROPIC_API_KEY"
        assert keys.key_count("anthropic") == 2

    def test_rotate_moves_to_backup_then_none(self) -> None:
        assert keys.rotate("anthropic", FAKE_ANTH_PRIMARY, "billing") == FAKE_ANTH_BACKUP
        assert keys.current_slot("anthropic") == "ANTHROPIC_API_KEY_BACKUP"
        assert keys.rotate("anthropic", FAKE_ANTH_BACKUP, "billing") is None
        assert not keys.has_key("anthropic")

    def test_rotate_is_idempotent_for_the_same_failed_key(self) -> None:
        results: list[str | None] = []

        def worker() -> None:
            results.append(keys.rotate("anthropic", FAKE_ANTH_PRIMARY, "billing"))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert results == [FAKE_ANTH_BACKUP] * 8
        assert keys.get_key("anthropic") == FAKE_ANTH_BACKUP

    def test_duplicate_values_count_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY_BACKUP", FAKE_ANTH_PRIMARY)
        keys.reset_keys()
        assert keys.key_count("anthropic") == 1

    def test_alias_env_names(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GROK_API_KEY", "xai-test-key-0000")
        keys.reset_keys()
        assert keys.current_slot("xai") == "GROK_API_KEY"
        assert not keys.has_key("gemini")

    def test_env_is_never_mutated(self) -> None:
        import os

        keys.rotate("anthropic", FAKE_ANTH_PRIMARY, "billing")
        assert os.environ["ANTHROPIC_API_KEY"] == FAKE_ANTH_PRIMARY


class TestPersistedMarkers:
    def test_new_process_skips_known_exhausted_key(self, tmp_path: Path) -> None:
        keys.rotate("anthropic", FAKE_ANTH_PRIMARY, "billing")
        keys.reset_keys()  # simulates a fresh process
        assert keys.current_slot("anthropic") == "ANTHROPIC_API_KEY_BACKUP"

    def test_state_file_holds_fingerprints_not_keys(self, tmp_path: Path) -> None:
        keys.rotate("anthropic", FAKE_ANTH_PRIMARY, "billing")
        raw = (tmp_path / "key_state.json").read_text()
        assert FAKE_ANTH_PRIMARY not in raw
        assert key_state.fingerprint(FAKE_ANTH_PRIMARY) in json.loads(raw)

    def test_expired_marker_is_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REFCHECK_EXHAUSTED_KEY_TTL_HOURS", "-1")
        keys.rotate("anthropic", FAKE_ANTH_PRIMARY, "billing")
        keys.reset_keys()
        assert keys.current_slot("anthropic") == "ANTHROPIC_API_KEY"

    def test_persistence_can_be_disabled(self, monkeypatch: pytest.MonkeyPatch,
                                         tmp_path: Path) -> None:
        monkeypatch.setenv("REFCHECK_KEY_STATE_FILE", "")
        keys.rotate("anthropic", FAKE_ANTH_PRIMARY, "billing")
        keys.reset_keys()
        assert keys.current_slot("anthropic") == "ANTHROPIC_API_KEY"
        assert not (tmp_path / "key_state.json").exists()

    def test_clear_persisted(self) -> None:
        keys.rotate("anthropic", FAKE_ANTH_PRIMARY, "billing")
        keys.reset_keys(clear_persisted=True)
        assert keys.current_slot("anthropic") == "ANTHROPIC_API_KEY"

    def test_corrupt_state_file_is_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "key_state.json").write_text("{not json")
        assert not key_state.is_marked(FAKE_ANTH_PRIMARY)


class TestClassifyError:
    def test_kinds(self) -> None:
        assert classify_error(billing_error()) == "billing"
        assert classify_error(auth_error()) == "auth"
        assert classify_error(not_found_error()) == "not_found"
        assert classify_error(rate_limit_error()) == "rate_limit"
        assert classify_error(litellm.exceptions.Timeout("slow", "m", "openai")) == "timeout"
        assert classify_error(
            litellm.exceptions.ServiceUnavailableError("overloaded", "anthropic", "m"),
        ) == "transient"
        assert classify_error(
            litellm.exceptions.InternalServerError("boom", "openai", "m"),
        ) == "transient"
        assert classify_error(
            litellm.exceptions.APIConnectionError("reset", "openai", "m"),
        ) == "transient"
        assert classify_error(
            litellm.exceptions.ContextWindowExceededError("too long", "m", "openai"),
        ) == "context_window"
        assert classify_error(
            litellm.exceptions.BadRequestError("bad schema", "m", "openai"),
        ) == "bad_request"
        assert classify_error(ValueError("weird")) == "other"

    def test_openai_insufficient_quota_is_billing_not_rate_limit(self) -> None:
        exc = litellm.exceptions.RateLimitError(
            "You exceeded your current quota (insufficient_quota)", "openai", "m",
        )
        assert classify_error(exc) == "billing"

    def test_api_error_status_codes(self) -> None:
        assert classify_error(litellm.exceptions.APIError(529, "overloaded", "a", "m")) == \
            "transient"
        assert classify_error(litellm.exceptions.APIError(402, "pay", "a", "m")) == "billing"


class TestRedaction:
    def test_loaded_keys_are_redacted(self) -> None:
        keys.get_key("openai")
        keys.get_key("anthropic")
        text = f"bad key {FAKE_OPENAI} and {FAKE_ANTH_BACKUP}"
        cleaned = redact(text)
        assert FAKE_OPENAI not in cleaned and FAKE_ANTH_BACKUP not in cleaned

    def test_key_shaped_tokens_are_redacted(self) -> None:
        assert "sk-proj-abcdef123456" not in redact("key sk-proj-abcdef123456 rejected")

    def test_short_error_is_redacted_and_truncated(self) -> None:
        keys.get_key("openai")
        message = short_error(auth_error(), limit=60)
        assert FAKE_OPENAI not in message
        assert len(message) <= 60


class TestLateEnv:
    def test_keys_added_after_first_lookup_are_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert not keys.has_key("gemini")
        monkeypatch.setenv("GEMINI_API_KEY", "AIza-test-0000000")
        assert keys.current_slot("gemini") == "GEMINI_API_KEY"
