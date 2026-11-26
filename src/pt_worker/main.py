"""Composition root: único lugar que conecta los servicios entre sí.

W1/W2: arma el cliente de la app, el buffer de eventos y el worker de LiveKit (agent_name
"whatsapp-agent"). Subcomandos de la CLI de LiveKit: `pt-worker dev` / `pt-worker start`.
"""

from __future__ import annotations

import sys

from pt_worker.app_client.http import HttpAppClient
from pt_worker.app_client.port import AppApi
from pt_worker.call_bridge.application.run_call import CallServices
from pt_worker.call_bridge.infrastructure.app_context import AppContextSource
from pt_worker.call_bridge.infrastructure.clock import MonotonicClock
from pt_worker.call_bridge.infrastructure.livekit.server import create_server, run_server
from pt_worker.call_events.application import TurnBuffer
from pt_worker.call_events.infrastructure import HttpCallEventSink
from pt_worker.config import ConfigError, Settings, get_settings


def build_app_client(settings: Settings) -> AppApi:
    return HttpAppClient(
        base_url=settings.app_base_url,
        token=settings.worker_api_token.get_secret_value(),
        timeout_context=settings.timeout_context_sec,
        timeout_write=settings.timeout_write_sec,
    )


def build_call_services() -> CallServices:
    """Dependencias de UNA llamada. Función de módulo (serializable); lee el entorno del job."""
    settings = get_settings()
    app = build_app_client(settings)
    return CallServices(
        context_source=AppContextSource(app),
        events=TurnBuffer(HttpCallEventSink(app)),
        clock=MonotonicClock(),
        close=app.aclose,
        default_voice=settings.default_voice,
        max_start_retries=settings.max_start_retries,
        start_backoff_sec=settings.start_retry_backoff_sec,
    )


def main() -> None:
    try:
        settings = get_settings()
    except ConfigError as exc:
        sys.stderr.write(f"{exc}\n")
        raise SystemExit(2) from None
    server = create_server(
        build_call_services,
        url=settings.livekit_url,
        api_key=settings.livekit_api_key.get_secret_value(),
        api_secret=settings.livekit_api_secret.get_secret_value(),
    )
    run_server(server)
