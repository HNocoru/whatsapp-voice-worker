# Imagen del worker de voz. Sin secretos: las variables se pasan en ejecución (--env-file).
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
RUN uv sync --frozen --no-dev

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"
RUN useradd --system --uid 10001 --create-home worker
WORKDIR /app
COPY --from=builder --chown=worker:worker /app /app
USER worker
# `start` es el modo producción de la CLI de LiveKit (main.py usa cli.run_app).
ENTRYPOINT ["pt-worker"]
CMD ["start"]
