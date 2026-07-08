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
# Shell form so $PORT (set by Render/Railway/Fly) is honored; falls back to 8000.
CMD uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
