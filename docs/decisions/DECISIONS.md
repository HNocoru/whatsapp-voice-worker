# Decisiones del worker (pt-worker)

## Decisiones
- **Repo aparte de la app** por despliegue en host distinto a Vercel (decisión del usuario).
- **Sin acceso a base de datos;** todo por HTTP a la app según `docs/04-worker-contract.md`.
- **Un proceso con servicios lógicos** (`call_bridge`, `call_events`, `tool_calling`, `app_client`,
  `health`) y hexagonal en cada uno; el motor de voz detrás del puerto `VoiceEngine`.
- **Phonic sobre LiveKit** como ruta primaria; Pipecat directo solo como contingencia.
- **Caliope (`api-caliope-core-s2s`) como referencia, no base;** vive en `reference/` y no se importa.
  Su voz LiveKit + Phonic no se probó con llamadas reales.
- **El tope de 5 min lo controla el worker;** el límite de Phonic es solo red de seguridad.
- **El resumen y la memoria los hace la app,** no el worker.

- **W0 · Settings sin prefijo y sin archivo dotenv:** los nombres son los de §9 (`LIVEKIT_URL`,
  `PHONIC_API_KEY`, ...). `config.py` no lee ningún dotenv; el host aporta el entorno (en local:
  `uv run --env-file <archivo> pt-worker`). Es perezosa y su error lista solo nombres, nunca valores.
- **W0 · El tiempo entra como parámetro al dominio:** `Call` recibe `now` (segundos monotónicos) y el
  puerto `Clock` vive en `call_bridge/application`; el reloj real, en `infrastructure`. Así el tope de
  5 min se prueba con reloj falso. Corte a `>=` (4:30 despedida, 5:00 colgar).
- **W0 · Reintentos en `app_client`:** 5xx, 429 y error de red con backoff y jitter; nunca otros 4xx
  (contrato). Los turnos y el `end` encolados en memoria quedan para `call_events` (W1).
- **W0 · import-linter:** `tool_calling` y `health` existen vacíos para que los contratos los cubran.
  La regla «nada importa `reference`» no se puede expresar en import-linter (no está en el grafo): la
  cubre una prueba por AST (`tests/test_architecture_rules.py`). Las violaciones deliberadas se prueban
  sobre una copia temporal, nunca en el repo.
- **W0 · Python 3.12:** `requires-python >=3.12` (AGENTS.md). 3.15 no se verificó con las ruedas de livekit.

## W1 · Spike de conexión (opción A: "hola" fijo sin Phonic)

API verificada en el paquete instalado (`.venv/lib/python3.12/site-packages/livekit/`, livekit-agents 1.8.13):
- `agents/worker.py`: `AgentServer(ws_url, api_key, api_secret, ...)` y `rtc_session(func, agent_name=...)`
  (solo admite una entrada; `agent_name` activa el despacho explícito). `agents/cli/cli.py`:
  `cli.run_app(server)` lee los subcomandos (`dev`, `start`, `console`) de `sys.argv`.
- `agents/job.py`: `JobContext.connect()`, `wait_for_participant()`, `job.metadata`, `room`,
  `delete_room()`, `shutdown(reason)`. `rtc.RemoteParticipant.attributes` (`rtc/participant.py`).
- `agents/voice/agent_session.py`: `AgentSession.start(agent, room=, room_options=)`, `say(text, *, audio=...)`,
  evento `close` con `CloseEvent.reason` (`voice/events.py`: `CloseReason.PARTICIPANT_DISCONNECTED`, `ERROR`, ...).
- **Cómo se dice "hola" sin modelo:** `AgentActivity.say` (`voice/agent_activity.py`) solo exige TTS si NO se
  pasa `audio=`. Se pasa un `AsyncIterable[rtc.AudioFrame]` leído de `assets/hola.wav`, pregrabado con
  `espeak-ng -v es-mx -w hola.wav "Hola"` (voz robótica; suficiente para el spike). `AgentSession()` sin
  llm/stt/tts/vad no se probó contra una sala real. No se llama a `generate_reply` (exigiría LLM). El texto del turno es "Hola".
- Solo se verificó localmente: lectura del WAV (30 tramos de 20 ms a 22050 Hz), nombre `whatsapp-agent` en el
  servidor y que el entrypoint se serializa (pickle) como `functools.partial` de funciones de módulo.
- **`RealtimeModel` de Phonic** (`livekit/plugins/phonic/realtime/realtime_model.py`, solo anotado para W2; no se conecta):
  `RealtimeModel(*, api_key, phonic_agent, voice, welcome_message, generate_welcome_message, project,
  default_language, additional_languages, multilingual_mode, audio_speed, phonic_tools, boosted_keywords,
  min_words_to_interrupt, generate_no_input_poke_text, no_input_poke_sec, no_input_poke_text,
  no_input_end_conversation_sec, websocket_timeout_sec, intelligence_level, phonic_model,
  is_welcome_message_interruptible, vad_*, enable_assistant_backchannel, pronunciation_dictionary,
  template_variables, enable_redaction, mcp_servers, configuration_endpoint, additional_params,
  external_id, configs_for_tools, forbid_speech_after_tool_call, conn_options)`; todos opcionales
  (`NotGivenOr`). Declara `supports_say=True`. No hay `S2SModel`.

Decisiones:
- **Puertos:** `VoiceEngine` (say / wait_for_hangup / hangup), `CallContextSource` y `CallEvents` viven en
  `call_bridge/application`; `call_events.TurnBuffer` cumple `CallEvents` por tipado estructural y solo
  `main.py` los conecta (R5). `call_events/infrastructure` usa `app_client.port` (no está en R5).
- **call_id (W2):** prioridad 1) metadata del job (JSON `{"call_id"}`), 2) atributo `call_id` del participante;
  debe ser UUID. Sin él: se cierra la sala sin saludar y se registra el error (no hay dónde reportar a la app).
- **Reintento:** `TurnBuffer` reintenta turnos y `end` cada 2 s hasta 120 s tras colgar; 409 se da por entregado.
  Si se agota, se descartan y se registra. Ningún error de la app lanza. Es en memoria: si el proceso muere se pierden.
- `run_call` no corta por tope de 5 min ni dice despedida (W3); la llamada termina cuando cuelga quien llama.
- Entrypoint: una instancia de dependencias por llamada (`main.build_call_services`), cerrada al terminar.

No verificado en W1 (requiere una llamada real de WhatsApp):
- **W1** acceso al Connector de WhatsApp en la cuenta; **W2** que `call_id` llegue por metadata o atributo
  (por eso se aceptan ambos); **W6** que no hagan falta puertos UDP entrantes.
- Que el saludo se oiga en el celular y que `close` llegue como `participant_disconnected` al colgar.
- Que `JobContext.delete_room()` (`hangup`) cierre la llamada de WhatsApp (W4).

### W1 · Correcciones tras verificación independiente
Verificado en el paquete instalado (livekit-agents 1.8.13, `.venv/lib/python3.12/site-packages/livekit/`):
- `Agent(instructions=...)`: `instructions` es obligatorio y solo-keyword (`agents/voice/agent.py:891-895`; `Agent.__init__`).
- `AgentSession()` sin llm/stt/tts: todos son `NOT_GIVEN` por defecto (`agents/voice/agent_session.py:411-421`);
  `say(text, audio=...)` en `agent_session.py:1608-1615`. Que arranque sin modelos contra una sala real **sigue sin probarse**.
- `job.metadata`: `JobContext.job` (`agents/job.py:517-519`) devuelve `agent.Job`, que tiene `metadata: str`
  (`protocol/agent.pyi:83`); puede venir vacío, por eso `resolve_call_id` tolera `""`.
- `RealtimeModel` de Phonic: `plugins/phonic/realtime/realtime_model.py` (firma anotada arriba, `__init__` en la línea 226; no se conecta).
- **Colgar durante el saludo:** `SpeechHandle.wait_for_playout` (`agents/voice/speech_handle.py:229-255`) solo espera un
  futuro; la sesión solo interrumpe background speeches al cerrar (`agent_activity.py:1703-1735`). Por eso `run_call`
  compite `engine.say` contra `engine.wait_for_hangup` (`asyncio.wait FIRST_COMPLETED`); si cierra primero, abandona
  el saludo y publica `end` con el motivo real (sin turno, porque no llegó a sonar).
- **Fallo al arrancar:** `handle_job` crea el motor y llama `start()` dentro del manejo de errores; si falla publica `end`
  `failed` con `error` = nombre del tipo de excepción (nunca el mensaje), borra la sala y siempre cierra servicios y hace `shutdown`.
- **Motivos de cierre:** PARTICIPANT_DISCONNECTED→`caller_hangup`; USER_INITIATED y TASK_COMPLETED→`completed`;
  ERROR, JOB_SHUTDOWN y desconocidos→`failed` con `error="voice_engine_failure"` (fijo, no sensible). JOB_SHUTDOWN se
  trata como fallo: el worker se apaga a media llamada, no es un cierre normal.
- **Reintento:** el plazo (120 s) se comprueba antes de cada intento, cada intento se acota con `asyncio.timeout` al
  tiempo restante y la última pausa se recorta al plazo. Total ≤ 120 s tras colgar.
- **`PHONIC_API_KEY` sigue siendo obligatoria** (decisión consciente): W1 no la usa, pero W2 sí y el despliegue
  ya la provee; no se toca `config.py` en esta corrección para no ampliar el alcance.

## W2 · Conversación real con Phonic (S2S)

Verificado en el paquete instalado (livekit-agents 1.8.13, livekit-plugins-phonic):
- `AgentSession(llm=RealtimeModel(...))` + `Agent(instructions=...)`; sin llm/stt/tts sueltos
  (`agent_session.py:417`, `agent.py:891`, `realtime_model.py:226`).
- Las `instructions` del Agent llegan como `system_prompt` de Phonic (`realtime_model.py:1267-1272`).
- El plugin **no** tiene `max_conversation_duration_sec`: el tope de 5 min es solo del dominio `Call`.
- Transcripción: el plugin emite `input_audio_transcription_completed` (`realtime_model.py:1474`); la sesión lo
  publica como `conversation_item_added` (`agent_activity.py:2367-2393`, `ChatMessage.role/text_content`).
  El motor se suscribe a `conversation_item_added`; los turnos pasan por `TurnBuffer` con `seq` desde 1.
- Despedida: `AgentSession.generate_reply(instructions=...)` (`agent_session.py:1642`) -> `system_message` en
  Phonic (`realtime_model.py:1122-1132`).

Decisiones:
- Puerto `VoiceEngine`: `on_turn`, `start_conversation(instructions, voice, template_variables, welcome_message,
  language)`, `say_goodbye`, `wait_for_hangup`, `hangup`. Sin tipos de livekit/phonic. `hola.wav` ya no se usa
  (el archivo sigue en `infrastructure/livekit/assets/`; borrarlo queda para quien tenga permiso).
- `application/conversation.py` arma instrucciones (negocio, contacto, memoria, últimos 10 turnos; la memoria se
  marca como datos, no órdenes) y `template_variables` (`business_name`, `contact_name`, `is_new_contact`).
  Sin contexto (404/caída) -> instrucciones genéricas y voz por defecto.
- Voz: `business.voice` (`roberto|eduardo`) -> `RealtimeModel.voice`; si falta o no es válida, `DEFAULT_VOICE`
  (config `default_voice`, "roberto").
- Saludo: el contrato no trae `welcome_message`, así que `generate_welcome_message=True` (lo genera el modelo).
- Tope: `_supervise` en `run_call`: despedida a `goodbye_at_seconds` (4:30), corte duro a `max_call_seconds` (5:00)
  con `hangup()` y `end` `time_limit`. Reloj y espera inyectables (`CallServices.sleep`).
- Arranque: primer intento + `MAX_START_RETRIES` (3) reintentos con `START_RETRY_BACKOFF_SEC` (5 s); si todo falla,
  `end` `failed` (solo el tipo de excepción) y `hangup`. `PHONIC_API_KEY` sigue requerida; el plugin la lee del entorno.

No verificado (necesita llamada real):
- Que Phonic acepte los ids de voz `roberto`/`eduardo` tal cual, y que `template_variables` sin placeholders en el
  prompt no moleste (la sintaxis de sustitución no se verificó; los datos van también en las instructions).
- Que el texto del asistente y el del usuario lleguen ambos por `conversation_item_added`; que la despedida suene;
  que `delete_room` cuelgue WhatsApp; el welcome generado.
- `uv run` falla en este árbol: `pyproject.toml` ya se llama `whatsapp-voice-worker` y uv_build espera
  `src/whatsapp_voice_worker/`. Falta `[tool.uv.build-backend] module-name = "pt_worker"` (fuera de mi alcance).
  Las verificaciones se corrieron con `.venv/bin`.

Pendiente con la sesión de la app (gentle-shell 01a20c84-0f1c-7467-a992-e9f805a53d9e):
- Si `GET context` incluirá un `welcome_message` (hoy no está en el contrato).
- Qué hace la app con `time_limit` y si espera un `error` en `end` para él.

Correcciones tras la verificación independiente (W2):
- `GET context`: timeout 8 s con un reintento (cambio 2026-11-27, pedido por la app; antes 3 s y un solo
  intento). Si fallan los dos se arranca con configuración genérica. `turns`/`end` conservan reintento y backoff.
- Snapshot del contexto en la metadata del job (clave `context`): el worker lo usa sin esperar el GET; si
  falta, es inválido o su `call_id` no coincide, cae al GET. Con snapshot hace un GET de comprobación en
  paralelo; un 409 cuelga la sala sin abrir `end`. Phonic puede haber arrancado ya (deuda aceptada).
  Log por llamada: fuente (metadata|http|ninguno), longitudes de faq/horario/prompt, sin texto del cliente.
- `TurnBuffer` borra los turnos entregados por `seq`, no por posición (con envíos en vuelo se perdían turnos).
- Todo texto del cliente (nombre, memoria, turnos recientes) va marcado como datos, no órdenes.
- `business.language` se valida contra una lista cerrada (`{"es"}`); si no coincide, `es`.
- El corte duro ocurre siempre que vence el temporizador (antes dependía de `is_over_limit`).
- PENDIENTE de llamada real (NO VERIFICABLE): arranque de Phonic y colgado durante el arranque.

## Docker y CI
- Dockerfile multi-stage (python:3.12-slim + uv, `uv sync --frozen --no-dev`), usuario no root, sin secretos
  en la imagen; arranca `pt-worker start` (subcomando `start` de la CLI de LiveKit). `.dockerignore` deja
  fuera reference/, tests/, docs/, .git, cachés y archivos de variables de entorno.
- CI (GitHub Actions, `contents: read`): sync --frozen, ruff, mypy, pytest, lint-imports, y un job que
  construye la imagen sin publicarla. No requiere secretos (las pruebas no usan red).
- Deuda: HEALTHCHECK. El healthcheck HTTP del worker (W4, módulo `health/`) sigue pendiente; mientras tanto el
  host debe reiniciar por código de salida.
- Deuda: `pip-audit` sigue sin añadirse al CI. RESUELTO: imagen base `python:3.12.16-slim@sha256`, `uv:0.13.7@sha256`,
  `setup-uv` con `version: 0.13.7` y acciones fijadas por SHA de commit (checkout v4.4.0, setup-uv v5.4.2).
  Al actualizar, resolver de nuevo el digest/SHA; no usar tags flotantes.

## Fiabilidad del corte (R4-002 y siguientes)
- `say_goodbye` va dentro de `asyncio.timeout(goodbye_timeout_sec)` (10 s): una despedida colgada ya no
  retrasa el temporizador de corte de las 5:00. Si vence o falla, solo se registra el tipo de excepción.
- El colgado (corte duro y fallo de arranque) usa un helper único: 3 intentos, `asyncio.timeout`
  (`hangup_timeout_sec`, 10 s) por intento y 1 s de pausa. Si se agotan, se registra a nivel error.
- Corte agotado: `ended_reason` sigue siendo `time_limit`, pero `end.error = "hangup_failed"` para señalar
  que la sala pudo quedar abierta. Es el campo `error` (string|null) de docs/04; no cambia el contrato.
- Avisado a la app; ver F3/F4 en docs/integration-findings.md.

## Revisión del contrato con la app (2026-11-27)
- 409 en GET context: no se abre Phonic, no se manda `end`, se cuelga la sala y `run_call` retorna.
  404/timeout/5xx siguen con configuración genérica.
- Turnos: single-flight por `call_id` (un POST `turns` en vuelo); los nuevos se acumulan y salen en el
  siguiente envío. Cierra R4-003 (payload creciente) y evita duplicados mientras la app no tenga UNIQUE.
- Contexto real de la app: `memory` vacío no genera bloque "Memoria"; sin `welcome_message`.
- El contrato (`04-worker-contract.md`) se actualizó con lo acordado; debe replicarse idéntico en
  prueba-tecnic. Hallazgos en `docs/integration-findings.md`.
- `main.py` ya no solo valida la configuración (corregida la deuda obsoleta de W0).
- Tope de 30 s a `wait_for_participant` (F15, `PARTICIPANT_TIMEOUT_SEC`): al vencer, `end` `failed` con
  `error="no_participant"` y `answered_at` null (si el `call_id` viene en la metadata del job), se cierra
  la sala y se libera el slot. 30 s (no 60): la ventana de aceptación de Meta es ~30-60 s y el job ya
  se despachó cuando terminó el accept, así que 30 s tras `connect` bastan para que entre el Connector.
  Orden del cierre: delete_room, `end` acotado a 20 s (con la app caída su reintento tardaría 120 s y
  retendría el slot; si no se entrega se registra como perdido), `shutdown` siempre, cierre de servicios.

## Deudas
- `pip-audit` (listado en el roadmap de W0) no se agregó; decidir si entra en el CI de W1.
- Un artefacto de la primera pasada con opencode dejó un `.importlinter` y un `.gitignore` que ocultaba
  `*.toml`/`*.yml`; ambos se corrigieron. Revisar con lupa lo que genere un agente externo.

## Por verificar
Ver `docs/02-architecture.md` §8 (W1–W7).
