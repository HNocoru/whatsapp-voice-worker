# Handoff: revisar los dashboards (LiveKit Cloud y Meta) para diagnosticar la llamada de WhatsApp

Para: OpenCode (o cualquier agente con navegador). **Solo observar y reportar. No cambiar nada.**
Repo: `/home/JH532004/Dev/products/pt-worker` (whatsapp-voice-worker). Fecha: 2026-11-27.

## Reglas duras
- **Solo lectura.** No cambies ningún ajuste, no desactives ni actives interruptores, no borres salas, no crees claves, no hagas llamadas de prueba, no pulses botones de "Save", "Delete", "Disable" ni "Regenerate".
- **No introduzcas contraseñas, códigos 2FA ni tokens.** Si aparece una pantalla de login, **para y avisa al humano**: él inicia sesión en el navegador y tú sigues. Nunca guardes ni pegues credenciales.
- **No copies al informe** access tokens, API keys, API secrets, App Secret ni el valor del `WORKER_API_TOKEN`. Si una pantalla los muestra, anota solo "visible" y el nombre del campo. Los identificadores públicos (nombre del proyecto, ids de sala, ids de llamada, UUID `call_id`) sí puedes copiarlos.
- No leas archivos llamados exactamente `.env` ni `.env.worker`. No hagas `git add`, commit ni push.
- Único archivo que puedes crear: `docs/dashboard-findings.md`.
- Si no tienes navegador o la herramienta falla, **no inventes**: escribe en el informe "NO VERIFICADO: sin navegador" y deja la lista de pasos para que el humano los haga y pegue capturas o texto.
- Cada afirmación del informe lleva: dónde la viste (URL o ruta de menús), la hora de la pantalla si la hay, y una frase o valor textual. Lo que no veas va como `NO VISTO`.

## Contexto
Una llamada de WhatsApp llega a la app (Next.js), que llama a `AcceptWhatsAppCall` de LiveKit. El accept **falló** con `invalid_argument 400`. La app dice que Meta respondió "API calls from the server require an appsecret_proof argument" (código 100) y que la app de Meta tiene activado "Require App Secret". Es **una hipótesis firme, no probada**: no sabemos si el Connector de LiveKit envía el proof. El worker (agente `whatsapp-agent`) recibió el job, esperó al participante de WhatsApp, no llegó, y cerró por tiempo. Detalles en `docs/integration-findings.md` (filas F14 y F15).

Datos de referencia (públicos):
- Proyecto LiveKit Cloud: `prueba-tecnic-eh7a23kx` (host `wss://prueba-tecnic-eh7a23kx.livekit.cloud`).
- Agente: `whatsapp-agent`. Las salas se llaman `call-<uuid>`.
- Última llamada fallida: fila `54a7ba81-f12e-4ab2-acde-62303809d44c` (sala `call-54a7ba81-...`), 2026-11-27 alrededor de las 09:45 UTC; hubo una llamada más tarde (14:24 UTC aprox.) con el error ya detallado.

## Parte 1: LiveKit Cloud (https://cloud.livekit.io)
Entra al proyecto `prueba-tecnic-eh7a23kx`. Para cada punto, anota lo que ves.
1. **Agents / Workers**: ¿aparece registrado el agente `whatsapp-agent`? ¿estado (activo, desconectado)? ¿cuántos workers? ¿versión o región?
2. **Sessions o Rooms** (historial): busca las salas `call-<uuid>` de hoy. Para cada una: hora de creación y de cierre, duración, **lista de participantes con su tipo** (agente, `CONNECTOR`, estándar, SIP), si alguno publicó audio, y el motivo de cierre si lo muestra.
3. **Agent dispatches / Jobs**: ¿se creó el despacho `AD_...` y el job `AJ_...`? ¿estado (accepted, running, completed, failed)? ¿hay metadata del despacho visible? (anota solo si contiene la clave `call_id`; no hace falta el valor).
4. **Logs / Observability / Telephony**: ¿hay entradas del Connector de WhatsApp (accept, connect, disconnect)? Copia los mensajes de error textuales, sin tokens.
5. **Configuración del proyecto**: ¿hay una sección de **Connectors** o **WhatsApp**? ¿Algún campo para el **App Secret** de Meta o para `appsecret_proof`? (¡no pegues valores!). ¿Plan del proyecto (Build, Ship...) y límites visibles?
6. **API keys**: ¿cuántas hay y cómo se llaman? (solo nombres, nunca los valores).

## Parte 2: Meta for Developers (https://developers.facebook.com/apps/)
Entra a la app de WhatsApp de este proyecto.
7. **App Settings > Advanced > Security**: ¿"Require App Secret" (o "Require proof ... API calls from the server") está en Sí o en No? **No lo cambies.** Anota la ruta exacta y el texto del interruptor.
8. **WhatsApp > Configuration** (webhooks): URL de callback (¿termina en el túnel de ngrok `accuracy-shrubbery-awhile.ngrok-free.dev`?), estado de verificación, y **campos suscritos**: ¿`calls` y `messages` están suscritos? ¿qué versión de API?
9. **WhatsApp > API Setup / Phone numbers**: número de prueba usado, su `phone_number_id` (público), estado, y si **Calling** está habilitado. Si hay una página "Call settings" / "Calling", anota: estado (ENABLED/DISABLED), horario de atención (call hours), permisos de llamada.
10. **Webhooks recientes / Logs** (App Dashboard > Webhooks o "Webhook delivery"): ¿hay entregas del campo `calls` de hoy? Códigos de respuesta que devolvió nuestra app (200, 4xx, 5xx) y reintentos.
11. **Access token**: ¿qué tipo usa la app (temporal de 24 h o de usuario del sistema permanente)? Solo el tipo y la fecha de caducidad si se muestra, **nunca el token**. (Un token temporal caducado también produce errores 400.)
12. **Versión de la Graph API** que usa la app y si coincide con la que soporta el Connector (v23.0 a v26.0 según la doc de LiveKit).

## Entregable: `docs/dashboard-findings.md`
1. Tabla: punto (1 a 12), qué viste, `OK` / `NO VISTO` / `NO VERIFICADO`, dónde (URL o menús).
2. **Conclusión corta**: según lo observado, ¿qué causa de las siguientes queda respaldada o descartada? (a) "Require App Secret" activo y el Connector sin `appsecret_proof`; (b) token de Meta caducado o de tipo incorrecto; (c) Calling no habilitado o fuera de horario; (d) webhook sin suscripción a `calls`; (e) otra. Distingue **observado** de **inferido**.
3. **Lo que el humano debe cambiar** (lista, sin que tú lo cambies), en orden de menor a mayor riesgo, y qué comprobar tras cada cambio.
4. **Lo que sigue sin poder verse** sin una llamada nueva.
5. Una línea `Risk:` y la lista de pantallas visitadas.
