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
