# Slices del worker

Cada slice termina con checks en verde y un guion de demo. Correspondencia con la hoja de ruta de la app
entre paréntesis.

## W0 · Esqueleto (antes del slice 02 de la app)
- Mover `api-caliope-core-s2s/` a `reference/api-caliope-core-s2s/`; excluirlo de ruff, mypy, pytest,
  import-linter y del paquete. Añadir `reference/README.md`: "solo lectura, nunca probado con llamadas reales".
- `pyproject.toml` propio: `livekit-agents`, `livekit-plugins-phonic`, `httpx`, `pydantic`,
  `pydantic-settings`; dev: `ruff`, `mypy`, `pytest`, `pytest-asyncio`, `import-linter`, `pip-audit`.
  Verificar versiones compatibles (W7).
- Estructura de `src/pt_worker/` (§2 de arquitectura) con módulos vacíos y contratos de import-linter.
- `config.py` (falla si falta una variable, sin imprimir valores), `main.py`, `app_client` con fake.
- Dominio `Call` + `CallLimits` con pruebas (incluye el tope de 5 min con reloj falso).
- **Hecho cuando:** checks en verde y una prueba que viola una regla rompe `lint-imports`.

## W1 · Spike de conexión (= app slice 02)
- Agente mínimo que, despachado por LiveKit, dice "hola" fijo **sin Phonic**.
- Confirmar W1, W2 y W6. Registrar en DECISIONS lo que se encontró.
- **Demo:** llamar al número de prueba desde un celular y escuchar el saludo.
- Si el Connector no está disponible: detener y decidir la contingencia con el humano.

## W2 · Conversación con Phonic (= app slice 04)
- Adaptador `VoiceEngine` con Phonic; instrucciones desde `GET context` (fake si la app aún no lo tiene).
- Turnos en lotes a `POST turns`; `POST end` al colgar. Confirmar W3 y W5.
- **Demo:** conversación real en español; los turnos llegan a la app (o al fake con log).

## W3 · Tope de 5 min y fallos (= app slice 04)
- Despedida a 4:30, colgar a 5:00, `max_conversation_duration_sec ≈ 320` de respaldo. Confirmar W4.
- Reintento de arranque de Phonic; colgar con `failed` si no se puede.
- **Demo:** llamada de 5 min termina con despedida; colgar a la mitad guarda transcripción parcial.

## W4 · Confiabilidad (= app slice 07)
- 2 llamadas simultáneas desde 2 teléfonos; heartbeat; despliegue en host; reinicio automático.
- **Demo:** 2 llamadas a la vez; matar el proceso y verlo volver.

## W5 · Herramientas (= app slice 10, opcional)
- `ToolGateway` + `HttpToolExecutor`; registrar `check_availability`, `book_appointment`, `request_human`.
