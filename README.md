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
| Price research | Google Places, Perplexity Search, direct evidence fetch, DeepSeek V4 Flash |
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

Deployments run `uv run alembic upgrade head` before the API starts. When the
runtime `DATABASE_URL` uses Supabase's transaction pooler, set
`DATABASE_MIGRATION_URL` to the direct port-5432 connection string.

## Demo offline

```bash
cd backend && uv run python -m app.scripts.seed   # ~300-customer fake fitness studio
```

Then upload `backend/app/scripts/sample_customers.csv` via the onboarding screen,
or hit `POST /api/integrations/csv/preview`.

## Competitor price research

Pulse includes an MVP local price research workflow at
`POST /api/competitor-prices/research` and the frontend `/pricing` page. Set
`GOOGLE_MAPS_SERVER_API_KEY` and `PERPLEXITY_API_KEY` server-side to enable the
full flow. Perplexity Search supplies grounded menu/order evidence, Sonar
structures competitors and handles strict JSON extraction, and Google Maps
geocoding verifies the requested radius.

```bash
GOOGLE_MAPS_SERVER_API_KEY=...
ENABLE_GOOGLE_PLACES_DISCOVERY=true
ENABLE_DIRECT_SOURCE_FETCH=true
THIRD_PARTY_FRESHNESS_MONTHS=18
STRICT_FREE_TIER=true

PERPLEXITY_API_KEY=...
ENABLE_PERPLEXITY_SEARCH=true
ENABLE_PERPLEXITY_SONAR=true
PERPLEXITY_SONAR_MODEL=sonar
PERPLEXITY_SONAR_MAX_TOKENS=1600
PERPLEXITY_SEARCH_CONTEXT_SIZE=high
PERPLEXITY_MAX_RESULTS=5
PERPLEXITY_MAX_QUERIES_PER_COMPETITOR=3
PERPLEXITY_MAX_TOKENS_PER_PAGE=2048
```

Identical research requests are cached for two hours. When `STRICT_FREE_TIER=true`,
fresh research runs are capped. Strict free-tier mode also limits fresh runs to
3 competitors and 3 source
attempts per competitor, stopping early after two independent sources corroborate
a price. Perplexity is required for grounded competitor discovery. If source-page
discovery fails, only already-known first-party URLs are used; the application
does not generate ungrounded competitors or prices.

The Pricing tab restores the latest report and recent median history, supports
CSV export, and can save a two-hour monitor. The Celery worker checks for due
pricing monitors every ten minutes and persists fresh research for trend and
material-change alerts.

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
