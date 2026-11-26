"""Adaptador de `CallContextSource` sobre el puerto de `app_client`."""

from __future__ import annotations

from typing import Any

from pt_worker.app_client.port import AppApi


class AppContextSource:
    def __init__(self, app: AppApi) -> None:
        self._app = app

    async def fetch(self, call_id: str) -> dict[str, Any] | None:
        return await self._app.get_context(call_id)
