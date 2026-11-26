# Spike W1/W2 — Voz: WhatsApp Calling API + LiveKit + Phonic

Fecha: 2026-11-26  
Estado: **Spike documental (Parte 1)**. No se ejecutó llamada real. Todo lo marcado como "Por verificar" requiere prueba en entorno real.

## Resumen ejecutivo

- **¿Se puede recibir una llamada de WhatsApp y llevarla a LiveKit?** Sí, por dos rutas oficiales: (A) **LiveKit WhatsApp Connector** (LiveKit Cloud, recomendado si la cuenta lo tiene) que puentea la llamada WebRTC de Meta a una LiveKit Room; (B) integración propia sobre la **WhatsApp Business Calling API** de Meta (Graph API + webhooks + SDP WebRTC). Ambas son viables en documentación; ninguna está probada en este repo.
- **¿El número de prueba de Meta (+1 555 / public test number) soporta llamadas?** **No es un bloqueo duro según docs oficiales**, pero tiene condiciones. Meta documenta que se pueden probar integraciones de Calling API con *public test numbers* y *sandbox accounts*; en test numbers la llamada está deshabilitada por defecto y debe habilitarse por settings. Las sandbox accounts de calling son solo para Tech Partners. **Requiere verificación en la cuenta real del proyecto** (ver §2).
- **Phonic con LiveKit Agents**: integración oficial vía `livekit-plugins-phonic` (`phonic.realtime.RealtimeModel`) dentro de `AgentSession`. Precio público: Starter $0.07/min (10 llamadas concurrentes), Pro $0.065/min ($200 mínimo mensual). El tope de 10 concurrentes del Starter coincide con el riesgo ya identificado para 2 llamadas simultáneas (RNF-01 es compatible; escalar requiere plan).
- **Alternativa si WhatsApp Calling no sirve**: llamada web/audio directa a LiveKit Room desde navegador/app (WebRTC estándar LiveKit), sin depender de Meta Calling API. Es la contingencia de menor riesgo técnico para la prueba.

**Recomendación:** Validar primero en la cuenta real si el número de prueba/negocio tiene Calling API habilitable y si la cuenta LiveKit tiene acceso al WhatsApp Connector. Si el Connector está disponible, usarlo (ruta A). Si no, evaluar ruta B (SDP propio) como spike W1 con riesgo alto, o caer a contingencia web (ruta C) para demostrar la voz end-to-end.

---

## 1) ¿Se puede recibir una llamada de WhatsApp y llevarla a LiveKit? ¿Cómo se pasa el `call_id`?

### 1.1 Lo que dice Meta (oficial)

La WhatsApp Business Calling API permite iniciar y recibir llamadas VoIP con usuarios de WhatsApp. Señalización por Graph API + webhooks (o SIP); media por WebRTC (ICE + DTLS + SRTP) por defecto.

- **Prerrequisitos**: número en Cloud API (no WhatsApp Business app), suscripción al webhook field `calls`, permiso `whatsapp_business_messaging`, messaging limit >= 2000 destinatarios únicos/día (exento para public test numbers/sandbox), habilitar Calling en el número.  
  Fuente: [Cloud API Calling](https://developers.facebook.com/documentation/business-messaging/whatsapp/calling)
- **Llamada entrante (user-initiated)**: WhatsApp usuario llama -> Meta envía webhook `calls` con `event: connect`, `id` (call id, ej. `wacid...`), `direction: USER_INITIATED`, y `session.sdp_type=offer`, `session.sdp`. El negocio debe responder con `pre_accept` (recomendado) y luego `accept` enviando SDP answer vía `POST /<PHONE_NUMBER_ID>/calls`. Hay ~30-60s para aceptar. Terminar con `action: terminate`.  
  Fuentes: [User-initiated calls](https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/user-initiated-calls), ref local `reference/whatsapp_docs/call_user_init.md`.
- **Webhooks**: suscribirse al campo `calls`. El webhook incluye `calls[].id`, `from`, `to`, `direction`, `event`, `session.sdp`.  
  Fuente: [Webhooks](https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks), [Calling reference](https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/reference).

**Implicación:** la media es WebRTC con SDP offer/answer. Llevarla a LiveKit "en crudo" implica un puente WebRTC/SIP que termine la negociación SDP de Meta y publique audio en una LiveKit Room. No es un simple SIP trunk estándar.

### 1.2 Ruta A — LiveKit WhatsApp Connector (oficial LiveKit Cloud)

LiveKit documenta un **WhatsApp Connector** que puentea WhatsApp Business Calling con LiveKit Rooms.

- **Disponibilidad**: "Connectors are available in LiveKit Cloud only. Self-hosted LiveKit servers are not supported, but your agents can run anywhere, including self-hosted infrastructure."  
  Fuente: [LiveKit WhatsApp Connector](https://docs.livekit.io/telephony/connectors/whatsapp/)
- **Prerequisitos**: proyecto LiveKit Cloud; número registrado en WhatsApp Business account; WhatsApp Cloud API access token; Meta Developer Account; app capaz de recibir webhooks de WhatsApp; permisos de llamadas habilitados en Meta (inbound: call hours; outbound: región soportada + permiso). Soporta WhatsApp Cloud API v23.0-v26.0.
- **Inbound flow**: usuario llama -> Meta envía webhook `call connect` con SDP offer -> tu app llama `AcceptWhatsAppCall` con `whatsappPhoneNumberId`, `whatsappApiKey`, `whatsappCloudApiVersion`, `whatsappCallId` (del webhook Meta), `sdp` offer, y opcionalmente `roomName`, `agents`, `participantIdentity/Name/Metadata/Attributes`, `waitUntilAnswered`. LiveKit acepta la llamada y la conecta a la Room.  
  Fuente: [WhatsApp Connector - Accepting inbound calls](https://docs.livekit.io/telephony/connectors/whatsapp/), [Connector APIs](https://docs.livekit.io/reference/telephony/connectors-api)
- **Outbound flow**: `DialWhatsAppCall` -> Meta webhook con SDP answer -> `ConnectWhatsAppCall`. Disconnect con `DisconnectWhatsAppCall` (obligatorio también cuando cuelga el usuario, usando `USER_INITIATED`).
- **Identificación participante**: WhatsApp participants tienen `kind = CONNECTOR` en LiveKit.

**Conclusión ruta A:** sí se puede llevar WhatsApp a LiveKit si la cuenta es LiveKit Cloud y el conector está habilitado/disponible. El puente SDP lo maneja LiveKit.

### 1.3 Ruta B — Integración propia (Meta Calling API directo)

Sin el Connector, el worker/app tendría que: recibir webhook `calls` de Meta, hacer `pre_accept/accept` con SDP answer generado por un stack WebRTC/SFU/bridge, y conectar ese media a LiveKit (p.ej. como participante WebRTC o vía gateway). Es técnicamente posible pero **alto riesgo / alto esfuerzo**: requiere manejo WebRTC completo, ICE/DTLS/SRTP, timing de 30-60s, y compatibilidad con el SDP de Meta. No hay evidencia en este repo de que exista ese bridge.

### 1.4 ¿Cómo se pasa el `call_id`?

Hay **dos IDs distintos** que no deben confundirse:

| ID | Dueño | Forma | Uso |
|---|---|---|---|
| Meta WhatsApp call id | Meta | `wacid...` en `calls[].id` | Correlacionar webhooks/acciones de llamada en Meta/Connector |
| App `call_id` | App (Supabase) | UUID de fila `calls` | Identificador interno del contrato HTTP worker<->app (`/api/internal/calls/{call_id}/...`) |

**Flujo esperado (coherente con docs/02, docs/04):**
1. Webhook Meta llega a la app.
2. App crea fila `calls` y obtiene `call_id` (UUID interno).
3. App despacha/agente LiveKit con `call_id` en metadata del job o atributo del participante. **Por verificar W2**: cómo lo expone exactamente el conector/dispatch en el job.
4. Worker lee `call_id` de metadata/atributo y llama `GET /api/internal/calls/{call_id}/context`.

**Con LiveKit WhatsApp Connector:** `AcceptWhatsAppCall` acepta `participantMetadata`, `participantAttributes`, `roomName`, `agents`. El `call_id` interno puede viajar como `participantMetadata`/atributo o en la metadata de dispatch del agente; la forma exacta debe validarse en W1/W2 (queda **Por verificar**).

---

## 2) ¿Qué exige Meta para llamadas? ¿Funciona en el número de prueba +1 555?

### 2.1 Requisitos oficiales (Meta)

- Número de negocio en **Cloud API**, no WhatsApp Business app.
- App suscrita al webhook field **`calls`**.
- Permiso `whatsapp_business_messaging`.
- Messaging limit de al menos **2,000** destinatarios únicos/día. **Excepción**: "Your business isn't required to have a daily messaging limit of 2,000 unique recipients to test Calling API features when using public test numbers and Sandbox accounts."  
  Fuente: [Cloud API Calling - Prerequisites / Testing](https://developers.facebook.com/documentation/business-messaging/whatsapp/calling)
- Habilitar Calling en el número (`POST /<PHONE_NUMBER_ID>/settings` con `calling.status=ENABLED`). Llamadas deshabilitadas por defecto.
- Para business-initiated: permiso del usuario, disponibilidad por país; el número del negocio debe estar en país soportado.
- Para user-initiated: disponible donde Cloud API esté disponible.

### 2.2 Número de prueba / +1 555

Evidencia oficial:

- "You can test your WhatsApp Calling integration using public test numbers and a sandbox WhatsApp Business account."  
- "Calling is disabled by default on test numbers. You must configure calling features in phone number call settings before using the Calling API on a test number."  
- "You obtain a public test number after completing the Get Started flow."  
  Fuente: [Cloud API Calling](https://developers.facebook.com/documentation/business-messaging/whatsapp/calling)
- Sandbox calling: "Sandbox accounts are only available to Tech Partners... To test calling, you must claim your sandbox account with the Cloud API and Calling feature..."  
  Fuente: [Set Up a Sandbox Account for Calling](https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/sandbox)

**Conclusión:** El **número de prueba público (+1 555 / public test number del flujo Get Started)** no es, por documentación, un "no soporta llamadas" absoluto. La doc dice explícitamente que se puede usar para probar Calling API, pero: (1) calling viene deshabilitado por defecto; (2) hay que habilitarlo por settings; (3) sandbox calling tiene restricción Tech Partner; (4) la UI/flujo real puede variar por tipo de cuenta/app. 

**Estado para este proyecto:** **NO BLOQUEADO por documentación, pero NO CONFIRMADO en la cuenta real**. Se debe verificar en el dashboard/app proporcionado si el número de prueba permite activar `calling.status=ENABLED` y recibir `calls` webhooks. Si la cuenta no permite habilitarlo, es bloqueo para la ruta WhatsApp real y se debe activar la contingencia (ver §4).

---

## 3) Phonic con LiveKit Agents: integración y costo/límites

### 3.1 Integración (oficial)

- Plugin: `livekit-plugins-phonic` (Python) / `@livekit/agents-plugin-phonic` (Node).  
  Instalar: `uv add "livekit-agents[phonic]~=1.8"` o `uv add livekit-plugins-phonic`.
- Uso: `AgentSession(llm=phonic.realtime.RealtimeModel(...))` o pasar el modelo como `llm` del Agent. Requiere `PHONIC_API_KEY`.
- Phonic es speech-to-speech (RealtimeModel). Las `instructions` del Agent se usan por LiveKit; la doc de Phonic/LiveKit indica que config de LiveKit sobreescribe settings de plataforma Phonic.  
  Fuentes: [LiveKit Phonic plugin guide](https://docs.livekit.io/agents/models/realtime/plugins/phonic/), [Phonic docs - With LiveKit](https://docs.phonic.ai/docs/build/with-livekit), [PyPI livekit-plugins-phonic](https://pypi.org/project/livekit-plugins-phonic/)

Ejemplo mínimo (docs oficiales):

```python
from livekit.agents import Agent, AgentSession, AgentServer, JobContext, cli
from livekit.plugins.phonic.realtime import RealtimeModel

class MyAgent(Agent):
    def __init__(self):
        super().__init__(instructions="...", llm=RealtimeModel(voice="sabrina"))

server = AgentServer()
@server.rtc_session()
async def entrypoint(ctx: JobContext):
    session = AgentSession()
    await session.start(agent=MyAgent(), room=ctx.room)
```

### 3.2 Costo / límites (público, verificar antes de compra)

Fuente: [Phonic pricing](https://phonic.ai/pricing) (consultado 2026-11-26):

| Plan | Precio/min | Mínimo | Concurrencia | Notas |
|---|---:|---:|---:|---|
| Starter | $0.07/min | No | 10 llamadas concurrentes | 10 agentes, 3 seats, voces ilimitadas |
| Pro | $0.065/min | $200/mes (~3100 min) | 50 concurrentes | Slack Connect |
| Enterprise | Custom | Custom | Custom | HIPAA/BAA, on-prem/VPC, etc. |

Observaciones:
- "No LLM pass-throughs. No per-token charges."
- Silencio >10s con 95% descuento (según FAQ pricing).
- **Riesgo RNF-01**: 2 llamadas simultáneas caben en Starter (10). OK para demo.
- **Riesgo W7**: verificar compatibilidad real de `livekit-agents` y `livekit-plugins-phonic` (versiones >=1.8,<2 en referencia).

---

## 4) Alternativa si WhatsApp no sirve: llamada web con LiveKit

Si el número de prueba/Meta Calling API no se puede habilitar o el Connector no está disponible:

- **Ruta C (contingencia recomendada para demo técnica)**: usar LiveKit Rooms directamente desde un cliente web/mobile (LiveKit SDK JS/React/Swift/etc.). El usuario se conecta a una room y el agente LiveKit+Phonic atiende igual. No requiere WhatsApp Calling API, no requiere aprobación de Meta, no requiere número telefónico.
- **Qué cambia**: el "teléfono WhatsApp" se reemplaza por un botón "Llamar" en web/app que crea/join a una room. El contrato interno worker<->app puede mantenerse casi igual (`call_id`, context/turns/end).
- **Qué se conserva**: LiveKit Agents, Phonic RealtimeModel, lógica de límites, turnos, contexto.
- **Qué se pierde**: prueba específica de canal WhatsApp Calling; se debe documentar como desviación de alcance.

Contingencia ya prevista en arquitectura: "si W1 falla: transporte de WhatsApp de Pipecat en un VPS..." (docs/02-architecture.md §8). Mi recomendación práctica para la prueba técnica es **Ruta C web LiveKit** antes que Pipecat+VPS, por menor superficie operativa.

---

## 5) Recomendación

1. **Confirmar en la cuenta real** (bloqueante de decisión, no de este documento): ¿el número de prueba/public test number del proyecto permite `calling.status=ENABLED` y suscripción a webhook `calls`? Si no, detener ruta WhatsApp y usar Ruta C.
2. **Confirmar LiveKit Cloud Connector**: si la cuenta LiveKit del proyecto tiene WhatsApp Connector disponible, tomar Ruta A. Es la menor complejidad para inbound WhatsApp.
3. **Mantener contrato `call_id` interno**: no usar el `wacid` de Meta como ID primario del dominio; mapearlo en la app y pasar el UUID interno al worker por metadata/atributos.
4. **No construir puente WebRTC propio** salvo que Ruta A no exista y Ruta C sea rechazada.
5. **Siguiente spike (W1)**: llamada mínima end-to-end con "hola" fijo sin Phonic, confirmando W1/W2/W6 de arquitectura.

## Evidencia / fuentes

- Meta Cloud API Calling: https://developers.facebook.com/documentation/business-messaging/whatsapp/calling
- Meta User-initiated calls: https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/user-initiated-calls
- Meta Calling settings: https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/call-settings
- Meta Calling sandbox: https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/sandbox
- LiveKit WhatsApp Connector: https://docs.livekit.io/telephony/connectors/whatsapp/
- LiveKit Connector APIs: https://docs.livekit.io/reference/telephony/connectors-api
- LiveKit Phonic plugin: https://docs.livekit.io/agents/models/realtime/plugins/phonic/
- Phonic + LiveKit: https://docs.phonic.ai/docs/build/with-livekit
- livekit-plugins-phonic (PyPI): https://pypi.org/project/livekit-plugins-phonic/
- Phonic pricing: https://phonic.ai/pricing
- Referencia local: `reference/whatsapp_docs/call_configs.md`, `reference/whatsapp_docs/call_user_init.md`, `reference/whatsapp_docs/Llamadas_a_la_API_de_la_nube.md`

## No verificado / riesgos

- **W1**: acceso real al WhatsApp Connector en la cuenta LiveKit del proyecto.
- **W2**: forma exacta en que `call_id` interno llega al agente (job metadata vs participant attribute) con Connector/dispatch.
- **W6**: puertos UDP entrantes no necesarios (depende de despliegue/connector; Connector es cloud-managed).
- **W7**: compatibilidad real hoy de `livekit-agents>=1.8,<2` y `livekit-plugins-phonic>=1.8,<2`.
- **Número de prueba Meta**: habilitación efectiva de calling en la cuenta/app concreta (docs dicen posible; cuenta puede tener restricciones).
- **Costos Meta**: pricing de llamadas WhatsApp Business puede variar por región/tipo; no se validó en esta fase.
