# 01 · Alcance del worker de voz

Contexto completo de la prueba: `prueba-tecnic/docs/01-requirements.md`. Aquí solo lo que toca al worker.

## Requisitos que cumple este repo

| ID app | Requisito | Qué hace el worker |
|---|---|---|
| RF-01 | La IA contesta llamadas en español de México | Sesión LiveKit + Phonic con voz mexicana (`roberto`/`eduardo`) |
| RF-05 | Guardar cuándo, cuánto, cómo terminó, transcripción y resumen | Envía turnos y fin de llamada a la app; la app hace el resumen |
| RF-06 | Memoria entre voz y texto | Pide el contexto a la app al iniciar y lo inyecta como instrucciones |
| RF-08 | Tope de 5 min | Despedida a 4:30, colgar a 5:00; límite de Phonic como red de seguridad |
| RNF-01 | 2 llamadas simultáneas | Un proceso atiende varias sesiones; probado con 2 teléfonos |
| RNF-02 | Disponible 24/7 una semana | Host siempre encendido, healthcheck, reinicio automático, heartbeat |
| RNF-07 | Latencia baja | Contexto antes de conectar (p95 < 800 ms); nada lento durante la llamada |

## Qué NO hace
- No recibe el webhook de Meta (lo recibe la app en Vercel y despacha la llamada a LiveKit).
- No guarda nada en base de datos ni conoce `tenant_id`.
- No responde mensajes de texto ni notas de voz (eso es la cascada STT → LLM de la app).
- No genera el resumen ni actualiza la memoria (lo hace la app al recibir `end`).
- No hace llamadas salientes, campañas, encuestas ni transferencias a humanos.

## Flujo de una llamada
1. Usuario llama al número de WhatsApp → Meta → webhook de la app.
2. La app crea `calls`, acepta la llamada vía el Connector de WhatsApp de LiveKit y despacha este agente
   con el `call_id`.
3. El worker: `GET context` → abre Phonic con instrucciones (negocio + memoria + últimos turnos) →
   saluda → conversa → envía turnos en lotes.
4. A las 4:30 inyecta la despedida; a las 5:00 cuelga si sigue abierta.
5. Al colgar (cualquiera de los dos lados): `POST end` con motivo y duración.

## Fallos
- Phonic no arranca (4004/4010/4429/5xx): un reintento; si falla, mensaje breve y colgar con
  `ended_reason=failed`. La app manda después un WhatsApp de seguimiento (eso es de la app).
- La app no responde `context`: seguir con configuración base genérica.
- La app no responde `turns`/`end`: reintentar en segundo plano; nunca cortar la llamada por eso.
