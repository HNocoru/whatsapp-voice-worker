"""Configuración del worker (pydantic-settings).

- Perezosa: importar este módulo no lee el entorno ni exige variables.
- Falla si falta una variable, mostrando solo los NOMBRES, nunca los valores.
- No lee ningún archivo dotenv: el entorno lo aporta el host (o `uv run --env-file`).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(Exception):
    """Configuración inválida o incompleta. El mensaje nunca incluye valores."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    livekit_url: str
    livekit_api_key: SecretStr
    livekit_api_secret: SecretStr
    phonic_api_key: SecretStr
    app_base_url: str
    worker_api_token: SecretStr
    worker_id: str

    # Timeouts por petición según docs/04-worker-contract.md (context y tools 3 s; turns y end 5 s)
    timeout_context_sec: float = 3.0
    timeout_write_sec: float = 5.0
    heartbeat_interval_sec: int = 30

    # Arranque de Phonic (W2): reintentos tras el primer intento y pausa entre ellos.
    max_start_retries: int = 3
    start_retry_backoff_sec: float = 5.0
    # Voz si la app no manda una válida (roberto | eduardo, docs/02 §7).
    default_voice: str = "roberto"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    try:
        return Settings()  # type: ignore[call-arg]  # los campos requeridos salen del entorno
    except ValidationError as exc:
        names = sorted({str(err["loc"][0]).upper() for err in exc.errors() if err["loc"]})
        msg = f"Configuración inválida o incompleta; revisa estas variables: {', '.join(names)}"
        raise ConfigError(msg) from None
