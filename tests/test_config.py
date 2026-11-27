"""Settings: perezosa, falla con nombres (nunca valores) y no lee archivos dotenv."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from pt_worker import config
from pt_worker.config import ConfigError, get_settings

REQUIRED = {
    "LIVEKIT_URL": "wss://example.livekit.test",
    "LIVEKIT_API_KEY": "lk-key-SECRET-1",
    "LIVEKIT_API_SECRET": "lk-secret-SECRET-2",
    "PHONIC_API_KEY": "phonic-SECRET-3",
    "APP_BASE_URL": "https://app.test",
    "WORKER_API_TOKEN": "token-SECRET-4",
    "WORKER_ID": "worker-1",
}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in REQUIRED:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()


def set_env(monkeypatch: pytest.MonkeyPatch, skip: str | None = None) -> None:
    for name, value in REQUIRED.items():
        if name != skip:
            monkeypatch.setenv(name, value)


def test_importing_config_does_not_require_env() -> None:
    sys.modules.pop("pt_worker.config", None)
    importlib.import_module("pt_worker.config")  # no debe lanzar sin variables


def test_loads_when_everything_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    set_env(monkeypatch)
    settings = get_settings()
    assert settings.worker_id == "worker-1"
    assert settings.timeout_context_sec == 8.0
    assert settings.timeout_write_sec == 5.0


def test_missing_variable_names_it_and_leaks_no_values(monkeypatch: pytest.MonkeyPatch) -> None:
    set_env(monkeypatch, skip="PHONIC_API_KEY")
    with pytest.raises(ConfigError) as info:
        get_settings()
    message = str(info.value)
    assert "PHONIC_API_KEY" in message
    assert not any(value in message for value in REQUIRED.values())
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__


def test_secrets_are_masked_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    set_env(monkeypatch)
    rendered = repr(get_settings())
    for name in ("LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "PHONIC_API_KEY", "WORKER_API_TOKEN"):
        assert REQUIRED[name] not in rendered


def test_settings_ignore_a_dotenv_file_in_the_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".env").write_text("WORKER_ID=from-dotenv\n")
    monkeypatch.chdir(tmp_path)
    set_env(monkeypatch)
    assert get_settings().worker_id == "worker-1"
    assert config.Settings.model_config.get("env_file") is None


def test_w2_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    set_env(monkeypatch)
    settings = get_settings()
    assert settings.max_start_retries == 3
    assert settings.start_retry_backoff_sec == 5.0
    assert settings.default_voice == "roberto"
