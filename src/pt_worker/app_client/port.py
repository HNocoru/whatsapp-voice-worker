"""Puerto del cliente de la app y errores comunes (contrato: docs/04-worker-contract.md)."""

from __future__ import annotations

from typing import Any, Protocol


class AppClientError(Exception):
    """Fallo al hablar con la app (red, 5xx agotado, 4xx)."""


class CallAlreadyEndedError(AppClientError):
    """La app respondió 409: la llamada ya terminó."""


class AppApi(Protocol):
    async def get_context(self, call_id: str) -> dict[str, Any] | None:
        """GET context. `None` si la app responde 404 (el worker usa configuración genérica)."""
        ...

    async def post_turns(self, call_id: str, turns: list[dict[str, Any]]) -> None: ...

    async def post_end(self, call_id: str, payload: dict[str, Any]) -> None: ...

    async def post_heartbeat(self, worker_id: str, active_calls: int, version: str) -> None: ...

    async def aclose(self) -> None: ...
