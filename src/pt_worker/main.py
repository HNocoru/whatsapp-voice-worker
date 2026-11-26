"""Composition root: único lugar que conecta los servicios entre sí.

W0: solo valida la configuración y arma el cliente de la app. El motor de voz se conecta en W1.
"""

from __future__ import annotations

import sys

from pt_worker.app_client.http import HttpAppClient
from pt_worker.app_client.port import AppApi
from pt_worker.config import ConfigError, Settings, get_settings


def build_app_client(settings: Settings) -> AppApi:
    return HttpAppClient(
        base_url=settings.app_base_url,
        token=settings.worker_api_token.get_secret_value(),
        timeout_context=settings.timeout_context_sec,
        timeout_write=settings.timeout_write_sec,
    )


def main() -> None:
    try:
        settings = get_settings()
    except ConfigError as exc:
        sys.stderr.write(f"{exc}\n")
        raise SystemExit(2) from None
    sys.stdout.write(f"pt-worker {settings.worker_id}: configuración válida (W0)\n")
