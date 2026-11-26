# 02 · Arquitectura del worker

**Etiquetas:** `Confirmado` · `Por verificar` (no construir encima sin spike) · `Decisión`.

## 1. Estilo

Un **proceso desplegable** organizado en **servicios lógicos**, al estilo del diseño de Caliope
(call bridge, call events, tool calling), con **hexagonal dentro de cada servicio**. `Decisión`

Por qué no varios procesos: los servicios lógicos ya dan lo que el negocio pedía en Caliope (cambiar
Phonic o LiveKit sin tocar la lógica de llamada) sin pagar varios despliegues, red interna ni trazas
distribuidas. Si un servicio necesitara escalar aparte, su frontera ya es un puerto.

## 2. Estructura

```
pt-worker/
├─ src/pt_worker/
│  ├─ call_bridge/          # la sesión de voz
│  │  ├─ domain/            # Call (máquina de estados), CallLimits, Turn
│  │  ├─ application/       # run_call (caso de uso), ports.py (VoiceEngine, CallContextSource)
│  │  └─ infrastructure/
│  │     ├─ livekit/        # entrypoint del agente, sesión, lectura de metadata del job
│  │     └─ phonic/         # model_factory: adaptador VoiceEngine con Phonic
│  ├─ call_events/          # turnos y fin de llamada hacia la app
│  │  ├─ application/       # TurnBuffer, publish_end; puerto CallEventSink
│  │  └─ infrastructure/    # HttpCallEventSink (usa app_client)
│  ├─ tool_calling/         # herramientas que invoca el agente (slice opcional)
│  │  ├─ application/       # ToolGateway; puerto ToolExecutor
│  │  └─ infrastructure/    # HttpToolExecutor
│  ├─ app_client/           # cliente HTTP único hacia la app: token, timeouts, reintentos
│  ├─ health/               # heartbeat + endpoint/healthcheck del proceso
│  ├─ config.py             # pydantic-settings
│  └─ main.py               # composition root: arma puertos con adaptadores
├─ tests/                   # unit (fakes, sin red), integration (contra app fake), smoke (manual)
├─ reference/api-caliope-core-s2s/   # SOLO LECTURA; excluido del paquete y de lint/tests
├─ docs/
└─ pyproject.toml
```

## 3. Puertos

| Puerto | Qué abstrae | Adaptador hoy |
|---|---|---|
| `VoiceEngine` | El modelo S2S (abrir sesión, instrucciones, decir, colgar, eventos de turno) | Phonic vía `livekit-plugins-phonic` |
| `CallContextSource` | Obtener negocio + memoria + turnos al iniciar | HTTP `GET context` |
| `CallEventSink` | Enviar turnos y fin de llamada | HTTP `POST turns` / `POST end` |
| `ToolExecutor` | Ejecutar herramientas del agente | HTTP `POST tools/{name}` |
| `Clock` | Tiempo (para probar el tope de 5 min sin esperar) | reloj real / reloj falso en tests |

## 4. Patrones
- **Strategy/Registry** para el motor de voz: cambiar Phonic es otro adaptador de `VoiceEngine`.
- **Máquina de estados** en `Call`: `connecting → active → ending → ended`; transiciones inválidas fallan.
- **Buffer con reintento** en `call_events`: los turnos no se pierden si la app tarda.
- **Composition root** en `main.py`; **fakes sobre mocks** en pruebas.

## 5. Reglas (import-linter)
1. `*/domain` no importa nada fuera de stdlib.
2. `*/application` no importa `infrastructure`, `livekit`, `phonic`, `httpx`.
3. `livekit` y `phonic` solo en `call_bridge/infrastructure`.
4. `httpx` solo en `app_client`.
5. Servicios independientes entre sí; solo `main.py` los conecta.
6. Nada importa `reference`.

## 6. Qué tomar de `reference/api-caliope-core-s2s` (y qué no)

| Pieza | Decisión |
|---|---|
| `media_bridge/infrastructure/livekit/` (agent, session, server, job_request) | Adaptar a `call_bridge/infrastructure/livekit` |
| `media_bridge/infrastructure/phonic/model_factory.py` | Adaptar |
| `media_bridge/domain/call.py`, `transcript.py`, `tools.py` | Adaptar |
| `media_bridge/application/start_call.py`, `record_turns.py`, `end_call.py`, `brief_compiler.py`, `ports.py` | Adaptar, cambiando repositorios Postgres por puertos HTTP |
| `tests/fakes.py` y pruebas de dominio | Como patrón |
| `persistence/pg_*`, `outbox/`, `relay_outbox.py`, `db/`, alembic, `shared/infrastructure/postgres` | **No** |
| `cases`, `dialer`, `messaging`, `web_client`, `sessions`, `post_call`, grafo/LangGraph | **No** |

## 7. Confirmado (documentación oficial, nov 2026)
- Phonic tiene plugin oficial de LiveKit; español; voces `roberto` y `eduardo` con acento mexicano;
  Starter con 10 concurrentes; `max_conversation_duration_sec` corta con 4505 (sin despedida);
  al arrancar puede cerrar con 4004/4010/4429.
- LiveKit documenta un Connector de WhatsApp que puentea el audio de la Calling API de Meta.
- En la integración por LiveKit, las `instructions` del agente reemplazan el system prompt de Phonic.

## 8. Por verificar

| # | Hipótesis | Spike |
|---|---|---|
| W1 | Tenemos acceso al Connector de WhatsApp de LiveKit en nuestra cuenta | W1 |
| W2 | El `call_id` llega al agente (metadata del job o atributo del participante) | W1 |
| W3 | El plugin de Phonic emite eventos de transcripción por turno de ambos lados | W2 |
| W4 | Inyectar la despedida a las 4:30 funciona (`generate_reply`/`say`) y colgar cierra la llamada de WhatsApp | W3 |
| W5 | El código de Caliope (`media_bridge`) funciona con audio real | W2 |
| W6 | El worker no necesita puertos UDP entrantes (solo salientes a LiveKit Cloud) | W1 |
| W7 | Versiones compatibles de `livekit-agents` y `livekit-plugins-phonic` | W0 |

Contingencia si W1 falla: transporte de WhatsApp de Pipecat en un VPS con IP pública y TURN + puente
propio a Phonic por WebSocket. No se construye de antemano.

## 9. Despliegue
Host de procesos siempre encendido (Fly.io, Railway o VPS; no planes que duermen). Healthcheck y
reinicio automático. Variables: `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`,
`PHONIC_API_KEY`, `APP_BASE_URL`, `WORKER_API_TOKEN`, `WORKER_ID`.
