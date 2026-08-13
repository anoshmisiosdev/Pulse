# Churnary

AI-powered customer retention for small local businesses. Churnary predicts
which customers are about to churn and automatically drafts AI-written win-back
campaigns — before the owner notices a problem.

> **Naming:** the product brand is **Churnary**; **Pulse** is the internal
> codebase name (repo, Python package, service ids, env prefixes). User-facing
> copy says Churnary; code keeps Pulse.

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

## Quick start (no Docker — full stack on SQLite)

Docker isn't required to run the whole product locally. Postgres is only needed
for pgvector (RAG retrieval, which degrades to "no context" without it), so a
throwaway SQLite file is enough for everything else.

```bash
# terminal 1 — API on :8000
cd backend
uv sync                                   # creates .venv, installs deps (Python 3.12)
SUPABASE_URL= DATABASE_URL="sqlite+aiosqlite:///./dev.db" DB_USE_PGBOUNCER=false DB_SSL= \
  uv run uvicorn app.main:app --reload

# terminal 2 — frontend on :5173
cd frontend
npm install
npm run dev
```

Two env overrides matter, and both are why a half-configured setup 401s:

- **`SUPABASE_URL=`** — with Supabase Auth unconfigured *and* `ENVIRONMENT` not
  `production`, the API serves a built-in demo tenant instead of demanding a
  Bearer token (`app/core/deps.py`). If `SUPABASE_URL` is set in `.env` but the
  frontend has no `VITE_SUPABASE_*`, the browser sends no token and every call
  fails with 401 — blank it locally, or configure both sides.
- **`DATABASE_URL`** — SQLite skips `alembic upgrade head` (`CREATE EXTENSION
  vector` isn't supported); the app's `create_all` on startup covers the schema.

`frontend/.env.local` already blanks `VITE_API_BASE_URL` so the browser calls
`/api` on the Vite dev server, which proxies to :8000 (`vite.config.ts`).

```bash
cd backend && uv run pytest   # scoring engine + adapter tests
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

Note the **"try sample data" button persists nothing** — it scores in memory, so
customers have no database row and the timeline and recovery features stay empty.
Upload a CSV through `/setup` to exercise those.

### Seeing a recovery locally

Recovery attribution only credits sends that actually went out, and local dev has
no Resend key (approving a send marks it `failed`), so the loop can't be closed
through the UI alone. This fakes the delivery + return, then runs real attribution:

```bash
cd backend
DATABASE_URL="sqlite+aiosqlite:///./dev.db" uv run python -m app.scripts.demo_recovery
```

It refuses to run against a non-local `DATABASE_URL` without `--force`, because it
writes fabricated sends, visits and transactions. Re-running is safe — attribution
is idempotent per customer.

## Competitor price research

Churnary includes an MVP local price research workflow at
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
