# Pulse — AI Customer Retention Platform

## What This Is

Pulse predicts which customers are about to churn and drafts AI-written win-back
campaigns to keep them — before the owner notices a problem. Target users are
non-technical owners of small local businesses (fitness studios, salons, med spas).

**Definition of Done:** an owner with zero technical skill can sign up → connect
Square or upload a CSV → within 2 minutes see which customers are at risk *and
why in plain English* → approve an AI-written win-back email → see it send → two
weeks later see "3 customers recovered, ~$640 saved" → and pay $199/mo via Stripe.
When scope is unclear, cut toward that sentence.

## Stack (do not substitute without a strong reason)

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, Alembic, Pydantic v2
- **Workers:** Celery + Redis
- **DB:** PostgreSQL 16 on AWS RDS (`pulse-db`, private VPC) + Supabase Auth.
  Schema is created by `create_all` in `app/main.py` on startup (idempotent);
  Alembic covers anything added since `20260709_0001`. See `infra/aws/README.md`.
- **RAG:** per-business knowledge (services, brand voice, past campaign examples)
  retrieved into campaign generation. Embeddings via AWS Bedrock (`cohere.embed-v4:0`),
  stored in `pulse-db` via `pgvector` (`app/models/knowledge.py`,
  `app/services/rag/`). Chat/copy generation is unchanged (TokenMart).
- **Frontend:** React 18 + Vite + TypeScript, Tailwind, shadcn/ui, Recharts
- **AI:** Anthropic `claude-sonnet-4-6`
- **Email/SMS/Billing:** Resend / Twilio / Stripe
- **Dev env:** `docker-compose.yml` is canonical (postgres, redis, api, worker, frontend)

## Architecture

### Adapter pattern (mandatory)
Every integration implements `integrations/base.py::DataSourceAdapter`. Downstream
code (scoring, campaigns, dashboard) **only** touches normalized Pydantic types
(`schemas/normalized.py`). Adding an integration requires **zero changes outside
`integrations/`**. CSV is the reference implementation; Square/Stripe are live;
Mindbody is a `NotImplementedError` stub.

### Scoring engine (`scoring/`)
A **transparent weighted heuristic** — not ML. Owners must trust the score.
`engine.py` is **pure functions, no side effects, no I/O**. Inputs are plain
dataclasses; outputs are `score (0–100)`, `band (low/med/high)`, and
`reasons: list[str]` in plain English (e.g. _"Visited 2x/week for 6 months, no
visits in 21 days"_) — reasons are a first-class product feature, surface them
everywhere. Weights/thresholds are configurable per vertical (`scoring/config.py`);
a med-spa client returning in 5 months is normal, a gym member gone 3 weeks is not.
The interface accepts a drop-in ML model later.

### Campaign generation (`campaigns/`)
Claude generates email/SMS copy and dashboard "why at risk" summaries. Request
strict JSON; parse defensively (strip fences, retry once, fall back to a static
template). **Never block the send pipeline on the LLM.** Default mode is
**approve-to-send**. Log every generation (prompt + output + model version).

### Models (`models/`) — multi-tenant from day one
`Business`, `User`, `IntegrationConnection`, `Customer` (deduped by email/phone),
`Transaction`, `Visit`, `EngagementEvent`, `RiskScore` (append-only log),
`Campaign`, `CampaignSend`, `AutomationRule`, `RecoveryAttribution`, `Subscription`,
`SyncRun`. Multi-location is a column, never a rewrite.

## Conventions & guardrails

- **Conventional commits**, small PR-sized changes.
- All secrets in `.env` (see `.env.example`). Never commit secrets. OAuth tokens
  are **Fernet-encrypted at rest** (`core/security.py`, key from `FERNET_KEY`).
- Every external call: timeout + retry/backoff + a logged `SyncRun` row.
- **CAN-SPAM:** unsubscribe link in every email. **TCPA:** no SMS before 9am /
  after 8pm local; honor STOP and the per-customer `do_not_contact` flag.
- **HIPAA:** never ingest medical/treatment data — only name, contact, visit
  timestamps, spend. Provide a per-business data-deletion endpoint.
- **Testing:** pytest + httpx (backend), Vitest (frontend). ≥70% coverage on the
  scoring engine and adapters — these are the trust-critical core.

## Pricing tiers (billing target)

| Tier | Price | Limits |
|---|---|---|
| Starter | $199/mo | 1 integration, 1,000 customers, email only |
| Growth | $299/mo | all integrations, 2,500 customers, email+SMS, automation |
| Pro | $499/mo | unlimited customers, multi-location ready |

14-day trial (card required), annual = 2 months free, `founders_rate` coupon.
Enforce limits in middleware: nag at 90%, never hard-block.

## Build order (each phase ends runnable + tested)

0. Skeleton — compose, FastAPI health, Vite app, CI ✅
1. Data core — models, CSV adapter, ingest + dedupe ✅
2. Scoring engine — pure functions, nightly job, risk badges ✅
3. Square integration — OAuth, sync, webhooks, incremental re-score
4. Campaigns — Claude generation, approve-to-send, Resend, unsubscribe
5. Automations + SMS — rule engine, Twilio, TCPA quiet hours, attribution
6. Billing + polish — Stripe tiers, onboarding flow, seed script

## Commands

```bash
docker compose up --build       # full stack
cd backend && uv sync           # backend deps (Python 3.12)
uv run uvicorn app.main:app --reload
uv run pytest                   # tests
uv run python -m app.scripts.seed   # offline demo data
cd frontend && npm install && npm run dev
```
