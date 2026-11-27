# 04 · Contrato HTTP entre la app y el worker de voz

**Este archivo existe idéntico en los dos repos** (`prueba-tecnic/docs/04-worker-contract.md` y
`pt-worker/docs/04-worker-contract.md`). Si cambia, se cambia en los dos en el mismo día y se anota
en `DECISIONS.md` de ambos.

Estado: **Propuesta v0**. Se implementa en el slice 02 (llamada contestada) y se completa en el 04.

## Principio

- La **app** es la única dueña de los datos (Supabase). El **worker** no tiene credenciales de base.
- El worker pide al iniciar la llamada y guarda durante y al terminar, siempre por HTTP a la app.
- La memoria del contacto y la configuración del negocio **no vienen de WhatsApp**: viven en la app.

## Autenticación

- Header `Authorization: Bearer <WORKER_API_TOKEN>`; el mismo secreto en ambos lados, solo en variables
  de entorno. Comparación en tiempo constante en la app.
- Rutas bajo `/api/internal/*`. Devuelven 401 sin token válido y nunca se llaman desde el navegador.
- Mejora posible (no ahora): firma HMAC del cuerpo con timestamp.

## Identificadores

- `call_id`: UUID de la fila `calls` que crea la app al recibir el webhook `calls/connect`.
  Viaja al worker como atributo del participante o metadata del job de LiveKit (**Por verificar**
  en slice 02: cómo exactamente lo expone el Connector de WhatsApp).
  Acordado 2026-11-27: la app lo manda en `agents[].metadata` de `AcceptWhatsAppCall` como JSON
  `{"call_id": "<uuid>"}`, con nombre de agente `whatsapp-agent`.
- **Snapshot del contexto (acordado 2026-11-27):** la misma metadata puede traer el contexto ya
  armado: `{"call_id": "<uuid>", "context": { ...mismo JSON que devuelve GET context... }}`
  (la app lo limita a 48 000 bytes). El worker lo usa sin esperar el GET si `context` es un objeto
  con `business` objeto y su `call_id` coincide con el del despacho; si no, ignora el snapshot y
  hace el GET. Con snapshot, el worker hace además un GET de comprobación en paralelo que no
  bloquea el arranque: si responde 409 cuelga la sala y no manda `end`.
- El worker nunca recibe ni envía `tenant_id`: la app lo deduce del `call_id`.

## Endpoints

### 1. `GET /api/internal/calls/{call_id}/context`
Lo llama el worker **antes** de abrir la sesión con Phonic. Presupuesto: p95 < 800 ms.

Respuesta 200:
```json
{
  "call_id": "uuid",
  "business": {
    "name": "string",
    "tone": "string",
    "faq": "string",
    "hours": "string",
    "voice": "roberto | eduardo",
    "language": "es"
  },
  "contact": { "display_name": "string | null", "is_new": true },
  "memory": { "summary": "string", "facts": {} },
  "recent_turns": [{ "role": "user | assistant", "channel": "text | voice", "text": "string", "at": "ISO-8601" }],
  "limits": { "max_call_seconds": 300, "goodbye_at_seconds": 270 }
}
```
Errores: 404 si `call_id` no existe; 409 si la llamada ya terminó. Ante 404, timeout o 5xx el worker
sigue con una configuración base genérica (la llamada no se cae por esto). Ante **409** el worker
**no conversa**: no abre Phonic, no manda `end` (la app ya cerró la llamada) y solo cuelga la sala.

Acordado 2026-11-27 (replicar idéntico en prueba-tecnic): `memory` puede ir vacío
(`{"summary": "", "facts": {}}`) hasta que exista el snapshot; `welcome_message` no existe (el saludo
lo genera el modelo).

### 2. `POST /api/internal/calls/{call_id}/turns`
Turnos de transcripción, **incrementales** (para no perderlos si la llamada se corta). Lotes pequeños.
```json
{ "turns": [{ "seq": 1, "role": "user | assistant", "text": "string", "started_ms": 1234 }] }
```
Idempotente por `(call_id, seq)`: reenviar el mismo `seq` no duplica. Respuesta 204.
Acordado 2026-11-27: la BD debe imponerlo con `UNIQUE (call_id, seq)` + `ON CONFLICT DO NOTHING`
(un filtro previo no cubre peticiones simultáneas). El worker además serializa: un solo POST `turns`
en vuelo por llamada.

### 3. `POST /api/internal/calls/{call_id}/end`
Al terminar la llamada.
```json
{
  "ended_reason": "completed | caller_hangup | time_limit | failed",
  "answered_at": "ISO-8601 | null",
  "ended_at": "ISO-8601",
  "duration_sec": 123,
  "error": "string | null"
}
```
Acordado 2026-11-27 (replicar idéntico en prueba-tecnic):
- `error` es texto libre y puede valer `"hangup_failed"` cuando el corte por tiempo no pudo colgar la
  sala (`ended_reason` sigue siendo `time_limit`).
- `ended_reason` solo acepta `completed | caller_hangup | time_limit | failed`; `hangup_failed` NUNCA
  va como `ended_reason`.
- Al recibir `end` con `time_limit`, la app llama `DisconnectWhatsAppCall(BUSINESS_INITIATED)` y debe
  ignorar el error si Meta ya terminó la llamada.

Acordado 2026-11-27 (replicar idéntico en prueba-tecnic):
- `error="no_participant"` con `ended_reason` `failed` y `answered_at` null significa que el llamante
  nunca entró a la sala en el tiempo límite (30 s por defecto). `duration_sec` es 0.

La app genera el **resumen** con su LLM de texto y actualiza `contact_memory`. Idempotente: un segundo
`end` del mismo `call_id` responde 200 sin cambios. `missed` lo marca la app (llamada no contestada),
no el worker.

### 4. `POST /api/internal/tools/{name}`
Estado 2026-11-27: **todavía no hay ruta de tools** (ni en la app ni en el worker).
Herramientas que el agente de voz invoca durante la llamada (slice 10, opcional).
```json
{ "call_id": "uuid", "arguments": {} }
```
Respuesta: `{ "ok": true, "result": {} }` o `{ "ok": false, "error": "string" }`. Presupuesto p95 < 800 ms.
Herramientas previstas: `check_availability`, `book_appointment`, `request_human`.

### 5. `POST /api/internal/workers/heartbeat`
Cada 30 s. `{ "worker_id": "string", "active_calls": 0, "version": "string" }`. Alimenta el indicador
de salud del dashboard. Respuesta 204. Estado 2026-11-27: el worker **aún no manda heartbeat**.

## Reglas de fallo en el worker

- Timeout por petición: 8 s por intento en `GET context` (un reintento tras el primero; sin
  snapshot el peor caso es ~16.6 s antes de arrancar), 3 s en tools, 5 s en turns y end.
- Reintento con backoff y jitter solo ante 5xx, 429 o error de red; nunca ante 4xx.
- `turns` y `end` se encolan en memoria del proceso y se reintentan hasta 2 min después de colgar.
- Ningún error de la app tumba una llamada en curso.

## Pendiente de decidir
- Si `end` también recibe la transcripción completa como respaldo (hoy: no; se arma con `turns`).
- Versionado del contrato: por ahora `v0` implícito; si cambia de forma incompatible, prefijo `/v1/`.
