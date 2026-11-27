# whatsapp-voice-worker

Worker de voz del asistente de WhatsApp (LiveKit + Phonic). Ver `AGENTS.md` y `docs/`.

## Correrlo en local (W2: conversación S2S con Phonic)

1. Crea un archivo de entorno **fuera del repo** (o ignorado por git) con estas variables
   (docs/02-architecture.md §9): `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`,
   `PHONIC_API_KEY`, `APP_BASE_URL`, `WORKER_API_TOKEN`, `WORKER_ID`.
   Opcionales: `MAX_START_RETRIES` (3), `START_RETRY_BACKOFF_SEC` (5), `DEFAULT_VOICE` (roberto).
2. Arranca el worker (subcomandos de la CLI de LiveKit: `dev` o `start`):

   ```bash
   uv run --env-file <archivo> pt-worker dev
   ```

3. El agente se registra con `agent_name="whatsapp-agent"` (despacho explícito): la regla de
   despacho/Connector de LiveKit debe apuntar a ese nombre. El `call_id` debe llegar en la metadata
   del job (`{"call_id": "<uuid>"}`) o como atributo `call_id` del participante.

## Probar el audio sin WhatsApp

Lo que se revisó en el paquete instalado (`livekit-agents`, `.venv/lib/python3.12/site-packages/livekit/agents/cli/`):

- `cli.run_app` delega en la CLI legada (`cli.py:435-442` -> `_legacy.run_app`), con subcomandos
  `console` (`_legacy.py:1671`), `start` (`:1729`), `dev` (`:1788`) y `connect` (`:1852`).
- **`pt-worker console` NO sirve tal cual.** Usa un job simulado (`fake_job=True`, sala `console-room`,
  `_legacy.py:1515`) sin participante ni metadata, y el micrófono/altavoz local se acopla a
  `AgentSession` vía `AgentsConsole`, no a la sala. `handle_job` hace `ctx.wait_for_participant()`
  (`server.py`) y se quedaría esperando; además exige un `call_id`. Faltaría un modo de prueba
  (call_id fijo y entrada/salida local) que NO está implementado; no se cambió código.
- **`pt-worker connect --room <sala>`** (`_legacy.py:1852-1925`) entra a una sala real ya existente
  (la crea si no existe) con `--url/--api-key/--api-secret` (o `LIVEKIT_*`) y `--participant-identity`.
  `handle_job` sí corre ahí, porque espera a un participante real.

Trazado de la sala (diagnóstico, `room_trace.py`): tras conectar, el worker registra en INFO líneas
`room_trace t=<s> remote=<n> identity=... kind=... state=...` cada 2 s durante 30 s, y `wait_start` /
`wait_done` (o `wait_failed`) alrededor de `wait_for_participant()`. Busca `kind=PARTICIPANT_KIND_CONNECTOR`
(`kind_details=['PARTICIPANT_KIND_DETAIL_CONNECTOR_WHATSAPP']`): si `remote=0` en todas las líneas, el
conector no entró a ESTA sala (puede ser un accept fallido, un despacho a otra sala u otra causa:
cruza con el log de la app y el dashboard de LiveKit); si aparece pero tarde, mira `t` frente a `wait_done`.
De atributos solo se registran las claves, nunca los valores.

Tope de espera (F15): si nadie entra en 30 s (`PARTICIPANT_TIMEOUT_SEC`) se cierra la sala, se intenta
publicar `end` `failed`/`no_participant` (máx. 20 s, para no retener el slot si la app está caída) y se
cierra el job.

Pasos (sala de prueba; NO VERIFICADO con audio real):

1. Arranca `uv run --env-file <archivo> pt-worker dev` (o `connect --room prueba`).
2. Entra a la misma sala con un cliente de LiveKit (p. ej. Agents Playground o una página con token) con
   un atributo de participante `call_id=<uuid>` o despachando el job con metadata `{"call_id": "<uuid>"}`.
   Sin `call_id` el worker cierra la sala (`missing_call_id`).
3. Habla y comprueba que Phonic contesta. NO VERIFICADO: el uso de Agents Playground con
   `agent_name="whatsapp-agent"` (despacho explícito) y que el atributo `call_id` se pueda fijar desde él;
   la calidad del audio solo se confirma con una llamada real.
4. La app (`APP_BASE_URL`) debe aceptar ese `call_id`, o apuntar a una app/mock de prueba.

## Imagen Docker

```bash
docker build -t whatsapp-voice-worker .
docker run --rm --env-file <archivo> whatsapp-voice-worker   # ejecuta `pt-worker start`
```

Las variables van **siempre** por `--env-file` (o el gestor de secretos del host), nunca dentro de la
imagen. El contenedor corre como usuario no root. No hay HEALTHCHECK todavía: el host debe reiniciar
el contenedor según el código de salida (`--restart on-failure`).

## Checks

```bash
uv run ruff check && uv run mypy src && uv run pytest -q && uv run lint-imports
```
