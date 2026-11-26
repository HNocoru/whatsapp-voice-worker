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

## Deudas
- `pip-audit` (listado en el roadmap de W0) no se agregó; decidir si entra en el CI de W1.
- `[project.scripts]` apunta a `pt_worker.main:main`, que en W0 solo valida la configuración.
- Un artefacto de la primera pasada con opencode dejó un `.importlinter` y un `.gitignore` que ocultaba
  `*.toml`/`*.yml`; ambos se corrigieron. Revisar con lupa lo que genere un agente externo.

## Por verificar
Ver `docs/02-architecture.md` §8 (W1–W7).
