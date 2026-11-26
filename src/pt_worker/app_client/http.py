"""Cliente HTTP hacia la app. Único módulo que usa `httpx`.

Reglas del contrato: Bearer token, timeouts por petición, reintento con backoff y jitter solo
ante 5xx, 429 o error de red; nunca ante otros 4xx.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from pt_worker.app_client.port import AppClientError, CallAlreadyEndedError


class HttpAppClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout_context: float = 3.0,
        timeout_write: float = 5.0,
        max_attempts: int = 3,
        backoff_base: float = 0.5,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._timeout_context = timeout_context
        self._timeout_write = timeout_write
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base
        self._sleep = sleep
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            transport=transport,
        )

    async def _request(
        self, method: str, path: str, *, timeout: float, json: Any = None
    ) -> httpx.Response:
        last: str = "sin intentos"
        for attempt in range(1, self._max_attempts + 1):
            try:
                resp = await self._http.request(method, path, json=json, timeout=timeout)
            except httpx.TransportError as exc:
                last = type(exc).__name__
            else:
                if resp.status_code != 429 and resp.status_code < 500:
                    return resp
                last = f"HTTP {resp.status_code}"
            if attempt < self._max_attempts:
                delay = self._backoff_base * 2 ** (attempt - 1)
                await self._sleep(delay + random.uniform(0, delay / 4))  # noqa: S311
        msg = f"{method} {path} falló tras {self._max_attempts} intentos ({last})"
        raise AppClientError(msg)

    @staticmethod
    def _raise_for_client_error(resp: httpx.Response, path: str) -> None:
        if resp.status_code == 409:
            raise CallAlreadyEndedError(path)
        if resp.is_error:
            msg = f"{path} respondió HTTP {resp.status_code}"
            raise AppClientError(msg)

    async def get_context(self, call_id: str) -> dict[str, Any] | None:
        path = f"/api/internal/calls/{call_id}/context"
        resp = await self._request("GET", path, timeout=self._timeout_context)
        if resp.status_code == 404:
            return None
        self._raise_for_client_error(resp, path)
        data: dict[str, Any] = resp.json()
        return data

    async def post_turns(self, call_id: str, turns: list[dict[str, Any]]) -> None:
        path = f"/api/internal/calls/{call_id}/turns"
        resp = await self._request("POST", path, timeout=self._timeout_write, json={"turns": turns})
        self._raise_for_client_error(resp, path)

    async def post_end(self, call_id: str, payload: dict[str, Any]) -> None:
        path = f"/api/internal/calls/{call_id}/end"
        resp = await self._request("POST", path, timeout=self._timeout_write, json=payload)
        self._raise_for_client_error(resp, path)

    async def post_heartbeat(self, worker_id: str, active_calls: int, version: str) -> None:
        path = "/api/internal/workers/heartbeat"
        body = {"worker_id": worker_id, "active_calls": active_calls, "version": version}
        resp = await self._request("POST", path, timeout=self._timeout_write, json=body)
        self._raise_for_client_error(resp, path)

    async def aclose(self) -> None:
        await self._http.aclose()
