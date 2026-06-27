# Pulse

AI-powered customer retention for small local businesses. Pulse predicts which
customers are about to churn and automatically drafts AI-written win-back
campaigns — before the owner notices a problem.

> **The product in one screen:** _"We found 14 customers at high risk, worth an
> estimated $2,100/year."_ Everything optimizes for time-to-that-screen.

## Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0 (async), Alembic, Pydantic v2 |
| Workers | Celery + Redis |
| Database | PostgreSQL 16 (Supabase), Supabase Auth |
| Frontend | React 18 + Vite + TypeScript, Tailwind, shadcn/ui, Recharts |
| AI | Anthropic `claude-sonnet-4-6` |
| Email / SMS | Resend / Twilio |
| Billing | Stripe Checkout + Customer Portal |

## Quick start (Docker)

```bash
cp .env.example .env          # fill in secrets (works offline with seed data)
docker compose up --build     # postgres, redis, api, worker, frontend
```

- API:       http://localhost:8000  (docs at `/docs`)
- Frontend:  http://localhost:5173

## Quick start (backend only, no Docker)

```bash
cd backend
uv sync                       # creates .venv, installs deps (pins Python 3.12)
uv run uvicorn app.main:app --reload
uv run pytest                 # scoring engine + adapter tests
```

## Demo offline

```bash
cd backend && uv run python -m app.scripts.seed   # ~300-customer fake fitness studio
```

Then upload `backend/app/scripts/sample_customers.csv` via the onboarding screen,
or hit `POST /api/integrations/csv/preview`.

## Repo layout

```
pulse/
├── docker-compose.yml
├── backend/          # FastAPI app, scoring engine, adapters, workers
│   ├── app/
│   │   ├── core/         config, db, auth, deps
│   │   ├── models/       SQLAlchemy ORM (multi-tenant)
│   │   ├── schemas/      Pydantic v2 + normalized adapter types
│   │   ├── integrations/ adapter pattern: csv, square, stripe, mindbody
│   │   ├── scoring/      transparent churn engine (pure functions)
│   │   ├── campaigns/    Claude generation + static fallbacks
│   │   ├── api/          routers
│   │   └── workers/      Celery tasks
│   └── tests/
└── frontend/         # Vite + React + TS
```

See [CLAUDE.md](CLAUDE.md) for architecture details and conventions.
