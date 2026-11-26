"""Adaptador HTTP de `CallEventSink`: usa el puerto de `app_client` (nunca httpx directo)."""

from __future__ import annotations

from typing import Any

from pt_worker.app_client.port import AppApi, CallAlreadyEndedError


class HttpCallEventSink:
    def __init__(self, app: AppApi) -> None:
        self._app = app

    async def send_turns(self, call_id: str, turns: list[dict[str, Any]]) -> None:
        try:
            await self._app.post_turns(call_id, turns)
        except CallAlreadyEndedError:
            return  # 409: la app ya cerró la llamada; reintentar no sirve

    async def send_end(self, call_id: str, payload: dict[str, Any]) -> None:
        try:
            await self._app.post_end(call_id, payload)
        except CallAlreadyEndedError:
            return
