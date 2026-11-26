"""Fake en memoria del cliente de la app, para pruebas de los demás servicios (sin red)."""

from __future__ import annotations

from typing import Any

from pt_worker.app_client.port import AppClientError


class FakeAppClient:
    def __init__(self, context: dict[str, Any] | None = None) -> None:
        self.context = context
        self.turns: dict[str, dict[int, dict[str, Any]]] = {}
        self.ends: dict[str, dict[str, Any]] = {}
        self.heartbeats: list[dict[str, Any]] = []
        self.fail_next: int = 0  # nº de llamadas siguientes que fallan (simula app caída)
        self.closed = False

    def _maybe_fail(self) -> None:
        if self.fail_next > 0:
            self.fail_next -= 1
            msg = "app caída (fake)"
            raise AppClientError(msg)

    async def get_context(self, call_id: str) -> dict[str, Any] | None:
        self._maybe_fail()
        return self.context

    async def post_turns(self, call_id: str, turns: list[dict[str, Any]]) -> None:
        self._maybe_fail()
        stored = self.turns.setdefault(call_id, {})
        for turn in turns:
            stored[turn["seq"]] = turn  # idempotente por (call_id, seq), como la app

    async def post_end(self, call_id: str, payload: dict[str, Any]) -> None:
        self._maybe_fail()
        self.ends.setdefault(call_id, payload)  # el segundo `end` no cambia nada

    async def post_heartbeat(self, worker_id: str, active_calls: int, version: str) -> None:
        self._maybe_fail()
        self.heartbeats.append(
            {"worker_id": worker_id, "active_calls": active_calls, "version": version}
        )

    async def aclose(self) -> None:
        self.closed = True
