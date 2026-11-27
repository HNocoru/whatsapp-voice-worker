# Handoff: investigar cómo conectar el worker con las llamadas de WhatsApp

Para: OpenCode (o cualquier agente con navegador o búsqueda web). Solo investigación y documentación.
Repo: `/home/JH532004/Dev/products/pt-worker` (whatsapp-voice-worker, paquete `pt_worker`).

## Reglas duras
- **Solo lectura del código.** Único archivo que puedes crear: `docs/research-whatsapp-connection.md`.
- No leas, imprimas ni toques ningún archivo llamado exactamente `.env` (hay API keys). No pegues secretos en el informe.
- No hagas `git add`, commit ni push.
- Cita **siempre** la URL y una frase textual de la fuente. Lo que no puedas confirmar en una fuente oficial va marcado `NO VERIFICADO`. No inventes nombres de campos ni de endpoints.
- Fuentes aceptadas, en este orden: documentación oficial de Meta (developers.facebook.com), de LiveKit (docs.livekit.io, github.com/livekit), de Phonic (docs.phonic.ai). Blogs solo como apoyo y marcados como tales.
- Fecha de hoy: 2026-11-27. Si una página muestra versión de API (Cloud API v23 a v26), anota cuál leíste.

## Contexto: cómo es el sistema
```
Usuario (WhatsApp)  ->  Meta Calling API  --webhook "calls"-->  APP WEB (Next.js, Vercel)
                                                                      |  AcceptWhatsAppCall (LiveKit server API)
                                                                      v
                                           LiveKit Cloud: WhatsApp Connector -> Room
                                                                      |  despacho del agente "whatsapp-agent"
                                                                      v
                                       WORKER (este repo, siempre encendido, Python)
                                         handle_job -> GET context a la app -> Phonic RealtimeModel (S2S)
                                         -> POST turns / POST end a la app
```
- La **app web** es dueña de los datos y recibe el webhook de Meta. El **worker** no recibe webhooks de Meta ni tiene base de datos (contrato HTTP en `docs/04-worker-contract.md`).
- El worker se registra en LiveKit con `agent_name="whatsapp-agent"`. Con ese nombre el despacho es **explícito**: nadie le manda trabajo si el despacho no nombra al agente.
- El worker espera un participante en la sala (`ctx.wait_for_participant()`, `src/pt_worker/call_bridge/infrastructure/livekit/server.py`) y busca un `call_id` (UUID de la app) en este orden: metadata del job (JSON `{"call_id": "..."}`), luego atributo `call_id` del participante (`src/pt_worker/call_bridge/application/call_id.py`). Sin UUID válido cierra la sala sin saludar.
- El motor de voz es `AgentSession(llm=phonic RealtimeModel)`; no hay STT, LLM ni TTS aparte.
- El corte duro del worker es `ctx.delete_room()`.

## Ya investigado (no lo repitas, solo úsalo)
`docs/spike-voice.md` y `reference/whatsapp_docs/` (`call_user_init.md`, `call_configs.md`, `Llamadas_a_la_API_de_la_nube.md`). Resumen: dos rutas, **A = LiveKit WhatsApp Connector** (LiveKit Cloud, preferida) y B = integración propia con SDP. Meta usa `calls[].id` (`wacid...`) y nosotros usamos un UUID propio. **Lo que quedó sin responder son las preguntas de abajo.**

## Preguntas a resolver (cada una con fuente, cita y veredicto)

### A. Despacho del agente y `call_id` (lo más urgente; cierra W2)
1. En `AcceptWhatsAppCall`, ¿cómo se pide que se despache nuestro agente? Campo exacto (`agents`, `RoomAgentDispatch`, `agentName`, `metadata`) y su forma en el SDK de servidor JS/TS (la app es Next.js) y en Python.
2. ¿Dónde aterriza lo que mandemos? Compara `participantMetadata`, `participantAttributes` y la `metadata` del dispatch del agente. Para cada una: ¿llega a `ctx.job.metadata` del worker, a `participant.metadata` o a `participant.attributes`? Con esto decimos cuál de nuestras dos vías de `call_id` es la correcta, y cuál sobra.
3. ¿Qué `kind` y `identity` tiene el participante de WhatsApp (`CONNECTOR`)? ¿`ctx.wait_for_participant()` lo devuelve o filtra por tipo? Mira el default de `kind` en `wait_for_participant` en el paquete instalado (`.venv/lib/python3.12/site-packages/livekit/agents/job.py`).
4. ¿Se puede fijar `roomName` desde la app? Recomendación de nombre de sala (por ejemplo `wa-<call_id>`) para correlacionar.

### B. Quién acepta la llamada y cuándo (tiempos)
5. Secuencia exacta entrante: webhook `connect` con SDP offer -> `pre_accept` -> `AcceptWhatsAppCall` -> `accept`. ¿Quién llama a qué: la app a Meta, la app a LiveKit, o LiveKit a Meta? ¿Qué credenciales de Meta (access token, phone number id, versión de la Graph API) debe tener la app y cuáles se mandan a LiveKit?
6. Ventana de aceptación (¿30 a 60 s?). ¿Conviene que el worker ya esté conectado y "caliente" antes? ¿Qué pasa si el despacho tarda más que la ventana? ¿`waitUntilAnswered` cambia algo?
7. ¿El `GET context` (p95 < 800 ms) puede ocurrir antes de aceptar la llamada, o solo después? Impacto en el saludo inicial.

### C. Colgar y cierre (hoy es el punto más débil del worker)
8. Si **el usuario cuelga**: ¿cómo se entera LiveKit y cómo se entera la app (webhook `terminate`)? ¿Se cierra la sala sola? ¿`DisconnectWhatsAppCall` es obligatorio también en ese caso (el spike dice que sí con `USER_INITIATED`)? ¿Quién lo llama, la app o el worker?
9. Si **el worker corta** (límite de 5 min): ¿`delete_room` termina la llamada de WhatsApp o hay que llamar `DisconnectWhatsAppCall` (y con qué `disconnect_reason`)? Si hace falta, ¿se puede llamar desde Python con `livekit-api` (¿ya es dependencia transitiva?) o debe hacerlo la app?
10. Si la llamada **no se contesta o falla**: estados y eventos de Meta que la app debe mapear a `ended_reason` (`completed | caller_hangup | time_limit | failed`; `missed` lo marca la app).

### D. Audio y Phonic
11. Formato de audio del Connector hacia la sala (códec, frecuencia, canales). ¿Phonic `RealtimeModel` espera algo concreto (16 kHz, 24 kHz)? ¿Se resamplea solo? Fuente en docs de LiveKit/Phonic o código del plugin (`livekit/plugins/phonic/realtime/realtime_model.py`).
12. Confirmar en docs de Phonic: voces `roberto` y `eduardo`, idioma `es`, límite `max_conversation_duration_sec` (corta con código 4505 sin despedida) y códigos de cierre 4004/4010/4429 al arrancar.
13. Con `generate_welcome_message` o `welcome_message`: ¿quién habla primero en una llamada entrante de WhatsApp? ¿Hay latencia de arranque conocida?

### E. Configuración de Meta (lo que tiene que preparar el humano)
14. Pasos exactos, en orden, para habilitar Calling en el **número de prueba público** (`+1 555...`): `calling.status=ENABLED`, suscripción al webhook field `calls`, permisos (`whatsapp_business_messaging`), horarios de atención (`call_hours`), callback permission. ¿El número de prueba tiene lista de destinatarios permitidos? ¿Hay requisitos extra para recibir llamadas (usuario debe tener WhatsApp con llamadas habilitadas)?
15. Diferencia entre señalización por **Graph API + webhooks** y por **SIP**. Confirma que el Connector de LiveKit usa la primera. Versiones de Cloud API que soporta el Connector.
16. Verificación de firma del webhook (`X-Hub-Signature-256`) y el handshake de verificación. Dato para la app, no para el worker, pero déjalo anotado.

### F. Configuración de LiveKit
17. ¿El WhatsApp Connector está disponible en todos los planes de LiveKit Cloud (incluido el gratuito)? ¿Hay que activarlo en el dashboard? Costo por minuto del conector, si lo hay.
18. ¿Los agentes pueden correr fuera de LiveKit (nuestro worker en un VPS o Fly.io)? Confirma qué conexiones son necesarias (solo salientes por WSS) y qué puertos UDP/TCP necesita el agente para el audio (hipótesis W6: no hacen falta UDP entrantes).
19. Variables que necesita el worker y de dónde salen: `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` (ya existen). ¿Falta alguna para el conector?

### G. Cómo probar sin gastar una llamada real
20. ¿Hay forma de simular una llamada entrante de WhatsApp o de probar el despacho con un participante normal (LiveKit CLI `lk`, Agents Playground, `lk dispatch create`) mandando `metadata` con un `call_id` de prueba? Pasos exactos y comandos, para poder validar worker + Phonic **antes** de tener Meta listo.
21. Qué logs debe ver el humano para saber que funciona: que el worker se registró, que recibió el job, que pidió el contexto, que el modelo de Phonic cargó, que habló, que mandó `POST turns` y `POST end`. Revisa qué registra nuestro código (`run_call.py`, `voice_engine.py`) y qué nivel de log hay que activar en `pt-worker dev`.

## Entregable
`docs/research-whatsapp-connection.md` con:
1. **Tabla de respuestas** (pregunta, respuesta corta, estado `OK` / `NO VERIFICADO`, fuente).
2. **Secuencia final recomendada** de punta a punta (diagrama de texto) con los campos exactos de cada llamada.
3. **Cambios que pide al worker** (lista, con archivo y motivo). No los implementes. Ejemplos de lo que puede salir: elegir una sola vía de `call_id`, llamar `DisconnectWhatsAppCall`, filtrar el tipo de participante.
4. **Cambios que pide a la app** (para la sesión de la app, `gentle-shell 01a20c84-0f1c-7467-a992-e9f805a53d9e`): qué manda en `AcceptWhatsAppCall`, a quién avisa del colgado, valores de `ended_reason`, y cómo propaga `call_id`.
5. **Checklist para el humano**, en orden, para la primera prueba real (Meta, LiveKit, app, worker).
6. **Plan de prueba de llamada**, con criterio de éxito en cada paso: el worker conecta, el modelo carga, el saludo se oye, la conversación responde, los turnos llegan a la app, el `end` llega con el motivo correcto, y el corte de 5 minutos.
7. Lista de **lo que sigue sin poder verificarse sin una llamada real**.

Termina con una línea `Risk:` y la lista de fuentes consultadas.
