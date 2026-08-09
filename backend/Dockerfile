# ── build stage: install production deps only ──────────────────────────────
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml ./
COPY uv.lock* ./
RUN uv sync --no-install-project --no-dev

COPY . .

# ── runtime stage: venv + source, no build caches or dev toolchain ─────────
FROM python:3.12-slim

# uv stays so docker-compose `command: uv run …` overrides keep working.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000
# Shell form so $PORT (set by Render/Railway/Fly) is honored. Production never
# starts on a stale schema; local/offline containers keep the previous soft-fail.
CMD if [ "$ENVIRONMENT" = "production" ]; then alembic upgrade head; \
    else alembic upgrade head || echo "alembic skipped — no database?"; fi && \
    uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
