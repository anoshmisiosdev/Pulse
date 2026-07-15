# Pulse — Code Review & Improvement Recommendations

**Date:** 2026-07-14  
**Scope:** Full-stack review (backend, frontend, infra, tests, security)

---

## Executive Summary

Pulse is a well-architected SaaS application. The separation of concerns (models → services → API → frontend), the normalized adapter pattern for integrations, the pure-function scoring engine, and the Pydantic v2 + SQLAlchemy 2.0 async stack are all strong choices. The test suite (76 backend + 6 frontend tests) covers the critical paths.

I implemented **8 critical fixes** directly in the codebase. The remaining **25 items** are documented below for follow-up, organized by priority.

---

## ✅ Critical Fixes Implemented

### 1. CORS allows all methods with credentials
**File:** `backend/app/main.py`  
**Before:** `allow_methods=["*"]`, `allow_headers=["*"]`  
**After:** `allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"]`, `allow_headers=["Authorization", "Content-Type", "X-Request-ID"]`  
Combined with `allow_credentials=True`, the wildcard methods were a security risk.

### 2. `.gitignore` didn't cover `frontend/.env`
**File:** `.gitignore`  
Changed `.env` → `**/.env` + `**/.env.*` glob so all env files (root and frontend) are ignored.

### 3. No production secret validation
**File:** `backend/app/core/config.py`  
Added a `@model_validator(mode="after")` that fails fast in production if `FERNET_KEY`, `SUPABASE_URL` are missing, or `SUPABASE_JWT_SECRET` is too short. Prevents silent misconfiguration on deploy.

### 4. Health endpoint didn't check dependencies
**File:** `backend/app/api/health.py`  
Replaced the unconditional `{"status": "ok"}` with a real `SELECT 1` DB probe. Returns HTTP 503 when the DB is unreachable so load balancers can route away from broken instances. Removed the model-name info leak.

### 5. No rate limiting on auth or research endpoints
**Files:** `backend/app/core/ratelimit.py` (new), `backend/app/main.py`  
Added a lightweight in-memory IP rate limiter middleware:
- `/api/auth`: 5 requests/60s (brute-force protection)
- `/api/competitor-prices`: 3 requests/60s (expensive LLM calls)
Returns 429 with `Retry-After` header. For multi-instance production, swap the in-memory store for Redis (interface stays the same).

### 6. Broken navigation link
**File:** `frontend/src/components/AppShell.tsx`  
Fixed the dropdown menu link from `/connect` (non-existent route) to `/setup` (the actual data sources page).

### 7. Deprecated `datetime.utcnow()`
**File:** `backend/app/scripts/demo_data.py`  
Replaced with `datetime.now(UTC)` (Python 3.12+ deprecation). Verified no remaining `utcnow` references in the codebase.

### 8. No `.dockerignore`
**File:** `.dockerignore` (new)  
Prevents `.venv`, `node_modules`, `.env` files, `.git`, Docker volumes, and IDE configs from entering the Docker build context — faster builds, no secret leakage into image layers.

---

## 🟡 Medium Priority — ✅ all resolved 2026-07-14

Items 9–22 were implemented (or found already fixed upstream):

- **9** — `persist_sync` now uses batched `IN (...)` lookups scoped to the incoming payload; memory is bounded by sync-batch size, not tenant history.
- **10** — `_to_risk`/`build_portfolio` moved to `app/services/portfolio_service.py`; no more cross-router private imports.
- **11** — hand-written `ALTER TABLE` patches moved to Alembic migration `20260714_0004`; container entrypoint now runs `alembic upgrade head` before uvicorn. `create_all` stays for brand-new DBs per the documented hybrid.
- **12** — already fixed upstream: `nightly_rescore` calls `refresh_scores` for every business.
- **13** — global exception handler in `main.py` logs the traceback and returns a consistent `{"error": "internal_error"}` envelope.
- **14** — JSON-in-Text columns are now `JSONB` on Postgres (plain `JSON` on SQLite tests); migration `20260714_0005` converts existing data; call sites store/read Python objects.
- **15+16** — `tenacity` now used: `app/core/http_retry.py` retries transient failures (network + 5xx, never 4xx) 3× with exponential backoff across Square/Stripe adapters, OAuth, LLM router, Perplexity, DeepSeek, and geocoding.
- **17** — `Pricing.tsx` split into `hooks/useCompetitorPricing.ts`, `components/pricing/PricingTable.tsx`, `components/pricing/MarketSummary.tsx`.
- **18** — `useMountProgress` deduped into `hooks/useMountProgress.ts`.
- **19** — `components/ErrorBoundary.tsx` wraps the app; render errors degrade to a reload card.
- **20** — all pages are `React.lazy` route chunks (main bundle 493 kB → 408 kB).
- **21** — already fixed upstream: the synthetic autopilot feed was replaced by real `api.listSends` data when outreach landed.
- **22** — JSON structured logging in production (`app/core/logging_setup.py`), plain text in dev; Celery keeps the same formatter.

<details><summary>Original findings (for reference)</summary>

### 9. `persist_sync` loads entire tenant into memory
**File:** `backend/app/services/ingest.py`  
`persist_sync` loads ALL existing customers, ALL transactions, and ALL visits into Python lists to check for duplicates. For a tenant with 10k+ customers and 100k+ transactions, this will OOM the container.

**Recommendation:** Replace the in-memory `seen_tx`/`seen_visits` sets with SQL `INSERT ... ON CONFLICT DO NOTHING` (PostgreSQL) or batched `SELECT ... WHERE external_id IN (...)` lookups.

### 10. Cross-module private API imports
**Files:** `backend/app/api/portfolio.py` line 49, `backend/app/api/integrations.py` line 52  
`from app.api.integrations import _to_risk` and `from app.api.portfolio import build_portfolio` create circular-ish dependencies between API routers. The underscore-prefix signals "private" but it's used across module boundaries.

**Recommendation:** Move `_to_risk` and `build_portfolio` into a `app/services/portfolio_service.py` module.

### 11. `create_all` + manual `ALTER TABLE` in lifespan instead of Alembic
**File:** `backend/app/main.py` lines 31–37  
The startup runs `Base.metadata.create_all` plus hand-written `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` patches. This is a schema-management anti-pattern.

**Recommendation:** Wire Alembic into the container entrypoint: `alembic upgrade head && uvicorn ...`. Remove the `create_all` + patch block from `lifespan`.

### 12. Celery `nightly_rescore` is a no-op
**File:** `backend/app/workers/celery_app.py`  
The beat-scheduled `nightly_rescore` task logs a message and returns `{"rescored": 0}`. It's never wired to `ingest.refresh_scores`. The product claims "nightly re-scoring" on the landing page but it doesn't happen.

**Recommendation:** Wire the task to iterate all businesses and call `refresh_scores`.

### 13. No global exception handler
**File:** `backend/app/main.py`  
Unhandled exceptions return FastAPI's default `{"detail": "Internal Server Error"}`. 

**Recommendation:** Register a global exception handler that logs the traceback and produces a consistent error envelope.

### 14. JSON stored as `Text` instead of `JSONB`
**Files:** `backend/app/models/customer.py` (`reasons`, `signals`), `competitor_price.py` (multiple `*_json` columns)  
JSON data is stored as `Text` and serialized/deserialized with `json.dumps`/`json.loads`. PostgreSQL's `JSONB` type supports indexing, querying, and validation natively.

### 15. `tenacity` installed but never used
**File:** `backend/pyproject.toml`  
`tenacity>=9.0` is listed but no file imports it. Meanwhile, the LLM client and DeepSeek client manually implement retry logic.

**Recommendation:** Either use `tenacity` for retry logic or remove it from dependencies.

### 16. No retry/backoff for external API calls
**Files:** `square_adapter.py`, `stripe_adapter.py`, `services/oauth.py`, `perplexity_client.py`, `deepseek_client.py`, `geocoding.py`  
Every external HTTP call is single-shot. Transient 5xx errors surface as hard failures.

### 17. Frontend `Pricing.tsx` is 600+ lines
**File:** `frontend/src/pages/Pricing.tsx`  
One file handles form state, API calls, elapsed-time tracking, table rendering, and confidence badges.

**Recommendation:** Extract into `hooks/useCompetitorPricing.ts`, `components/PricingTable.tsx`, `components/MarketSummary.tsx`, etc.

### 18. `useMountProgress` duplicated
**Files:** `frontend/src/pages/Dashboard.tsx` line 16, `Landing.tsx` line 10  
Same RAF-based hook copy-pasted in two files.

**Recommendation:** Move to `frontend/src/hooks/useMountProgress.ts`.

### 19. No React error boundary
An unhandled error in any component crashes the entire SPA to a white screen.

### 20. No code splitting / lazy loading
All pages are bundled into one chunk. The landing page and pricing page load even for users who only visit the dashboard.

### 21. `PulseContext` generates fake activity
**File:** `frontend/src/context/PulseContext.tsx` lines 174–195  
The "autopilot feed" is synthetic — maps at-risk customers to hardcoded `RELATIVE_TIMES` strings and marks them as "sent" if the rule mode is `auto`. This is misleading in a product that claims to send win-back emails on autopilot.

### 22. No structured logging
The backend uses stdlib `logging` with `basicConfig`. No JSON structured logging for production observability (CloudWatch, Datadog).

</details>

---

## 🟢 Low Priority / Code Quality

### 23. `render.yaml` model mismatch
`render.yaml` sets `TOKEN_ROUTER_MODEL=claude-opus-4-8` but `.env.example` and `config.py` default to `claude-sonnet-4-6`. Different model between environments.

### 24. JWKS client uses mutable global
`backend/app/core/security.py` line 65 — `_jwks_client = None` is module-level, initialized lazily without a lock. Use `functools.lru_cache`.

### 25. No multi-stage production Docker build
`backend/Dockerfile` — single-stage build includes the entire dev toolchain in the final image.

### 26. Tests use SQLite, production uses PostgreSQL
`backend/conftest.py`, `test_ingest.py` — behavioral differences (JSONB, ON CONFLICT, case sensitivity) aren't caught.

### 27. `conftest.py` NOW is hardcoded
`NOW = datetime(2026, 6, 26)` will become increasingly distant from "today".

### 28. Inline styles instead of Tailwind / CSS variables
Nearly every frontend component uses `style={{ background: "var(--surface)" }}` inline. Verbose, not refactorable via search/replace.

### 29. Magic numbers for confidence thresholds
`frontend/src/pages/Pricing.tsx` line 539 — `value >= 0.75`, `value >= 0.5` are inline. Should be constants.

### 30. `api.ts` has no retry logic
All `fetch` calls are single-shot. Transient network errors surface as failures.

### 31. No loading skeletons
Pages show nothing or "Loading…" text while waiting for API responses. Skeleton screens would improve perceived performance.

### 32. `Onboarding.tsx` appears to be a duplicate of `Setup.tsx`
Both files implement the same data-source connection flow with nearly identical UI. `Onboarding.tsx` falls back to `reloadDemo()` for non-CSV sources, while `Setup.tsx` has the real OAuth + API key flow. One should be removed.

### 33. Landing page brand name mismatch
The repo and README call the product "Pulse", but the frontend (AppShell, Landing, Login) consistently renders "Churnary". The `index.html` title is "Churnary — Customer Retention". This should be reconciled.

---

## Test Verification

After all fixes:
- **Backend:** 76 tests pass ✅ (`uv run pytest -q`)
- **Frontend:** 6 tests pass ✅ (`npx vitest run`)