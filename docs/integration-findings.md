# Hallazgos de integración worker ↔ app (2026-11-27)

Revisión del contrato `04-worker-contract.md` con la sesión de la app. Evidencia como `path:línea`.

| id | hallazgo | quién corrige | estado | evidencia |
|----|----------|---------------|--------|-----------|
| F1 | El 409 de GET context seguía con config genérica: el worker conversaba en una llamada terminada | worker | corregido (T1) | `src/pt_worker/call_bridge/application/run_call.py:77`; `tests/test_run_call.py` (test_context_409_*) |
| F2 | Turnos reenviados mientras otro envío seguía en vuelo; la app no tiene UNIQUE(call_id, position) | worker: corregido (T2, single-flight). app: pendiente UNIQUE + ON CONFLICT DO NOTHING | worker corregido / app pendiente | `src/pt_worker/call_events/application/__init__.py:60`; `tests/test_call_events.py` |
| F3 | `ended_reason` solo admite 4 valores; `hangup_failed` va en `error` | worker/app | OK (compatible) | `src/pt_worker/call_bridge/application/run_call.py:33,209`; `docs/04-worker-contract.md` §3 |
| F4 | `end` con `time_limit` debe provocar `DisconnectWhatsAppCall(BUSINESS_INITIATED)` ignorando error si Meta ya terminó | app | pendiente | `docs/04-worker-contract.md` §3 |
| F5 | Carrera entre webhook terminate de Meta y `end` del worker (duración, resumen): ¿cuál manda? | app (pregunta abierta) | pendiente | `docs/04-worker-contract.md` §3 |
| F6 | Confirmar que app y worker usan el mismo proyecto LiveKit | app + worker | pendiente confirmar | `docs/04-worker-contract.md` (Identificadores) |
| F7 | Heartbeat no implementado en el worker | worker (W4) | pendiente | `src/pt_worker/app_client/port.py:25` (el método existe en el puerto, `http.py` y `fake.py`, pero nadie lo llama) |
| F8 | No existe ruta de tools | worker + app (W5) | pendiente | `docs/04-worker-contract.md` §4 |
| F9 | `memory` siempre vacío; el snapshot no existe | app (slice 05) | pendiente | `tests/test_w2_conversation.py` (REAL_APP_CONTEXT) |
| F10 | Ninguna llamada real de WhatsApp probada de punta a punta | ambos | pendiente | `docs/decisions/DECISIONS.md` |
| F11 | En fallo de arranque, si el cuelgue falla, el `end` ya salió con `error` del arranque y la app no sabe que la sala quedó abierta | worker | pendiente | `src/pt_worker/call_bridge/application/run_call.py:94-98` |
| F12 | DECISIONS.md decía que `main` solo valida la configuración | worker | corregido | `docs/decisions/DECISIONS.md` (Deudas) |
