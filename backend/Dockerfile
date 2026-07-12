FROM python:3.12-slim

# uv for fast, reproducible installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Install deps first for layer caching
COPY pyproject.toml ./
COPY uv.lock* ./
RUN uv sync --no-install-project --all-extras --dev || uv sync --no-install-project

COPY . .

EXPOSE 8000
# Apply committed schema changes before serving traffic. Alembic uses
# DATABASE_MIGRATION_URL when supplied, otherwise DATABASE_URL.
# Shell form also lets Render/Railway/Fly provide $PORT.
CMD uv run alembic upgrade head && exec uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
