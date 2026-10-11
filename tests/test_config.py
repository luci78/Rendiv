from pathlib import Path

import pytest

from rendiv_api.config import Settings


def test_settings_read_only_allowlisted_non_secret_environment(monkeypatch):
    monkeypatch.setenv("RENDIV_APP_ENV", "test")
    monkeypatch.setenv("RENDIV_DATABASE_PATH", "/tmp/rendiv-test.sqlite3")
    monkeypatch.setenv("RENDIV_SQLITE_BUSY_TIMEOUT_MS", "1200")
    monkeypatch.setenv("UNUSED_SECRET", "must-not-be-read-or-logged")

    settings = Settings.from_environment()

    assert settings.app_env == "test"
    assert settings.database_path == Path("/tmp/rendiv-test.sqlite3")
    assert settings.sqlite_busy_timeout_ms == 1200
    assert "UNUSED_SECRET" not in Settings.model_fields


def test_settings_reject_invalid_environment_value(monkeypatch):
    monkeypatch.setenv("RENDIV_SQLITE_BUSY_TIMEOUT_MS", "not-an-integer")

    with pytest.raises(ValueError, match="invalid Rendiv application configuration"):
        Settings.from_environment()
