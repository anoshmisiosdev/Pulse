# Deploying Pulse

Three pieces:

| Piece | Host | What |
|---|---|---|
| Frontend | **Vercel** | React/Vite SPA (`frontend/`) |
| Backend | **Render / Railway / Fly** | FastAPI + Celery worker + Redis (Docker, `backend/`) |
| Database + Auth | **Supabase** | Postgres + Supabase Auth (email/password + Google) |

```
Browser ──login──▶ Supabase Auth ──JWT──▶ Browser
Browser ──Bearer JWT──▶ FastAPI (verifies JWT) ──▶ Supabase Postgres
```

---

## 1. Supabase (database + auth)

1. Create a project at supabase.com. Grab from **Project Settings → API**:
   - Project URL → `SUPABASE_URL` (backend) and `VITE_SUPABASE_URL` (frontend)
   - `anon` public key → `VITE_SUPABASE_ANON_KEY` (frontend)
   - JWT secret (if shown / legacy HS256) → `SUPABASE_JWT_SECRET` (backend). New
     projects verify via JWKS automatically — leave it blank.
2. **Auth → Providers**: enable Email, and Google (add your OAuth client ID/secret).
   Under **URL Configuration**, add your Vercel domain to the redirect allow-list.
3. **Database → Connect**: copy two connection strings:
   - *Transaction pooler* (port 6543) → runtime `DATABASE_URL`, with `DB_USE_PGBOUNCER=true`
   - *Direct* (port 5432) → used for migrations only
   Prefix the driver: `postgresql+asyncpg://...`

### Run migrations (against the DIRECT url)

```bash
cd backend
DATABASE_URL="postgresql+asyncpg://postgres:<pw>@db.<ref>.supabase.co:5432/postgres" \
  uv run alembic revision --autogenerate -m "init"
DATABASE_URL="...:5432/postgres" uv run alembic upgrade head
```

Each business is a tenant; a user's `business_id` defaults to their Supabase user id
(set `business_name` at signup — the login page does this automatically).

## 2. Backend → Render (Blueprint)

`render.yaml` defines the API (web), the Celery worker, and Redis. In the Render
dashboard: **New → Blueprint**, point at this repo. Then set the `sync: false`
secrets: `DATABASE_URL` (pooler url), `SUPABASE_URL`, `SUPABASE_JWT_SECRET` (if HS256),
`EXTRA_CORS_ORIGINS` (your Vercel domain), `FERNET_KEY`, `TOKEN_ROUTER_*`.

> Railway/Fly work too — both build `backend/Dockerfile`. Start command:
> `uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Add a Redis addon and
> a second "worker" process running the `celery … worker --beat` command.

Generate a Fernet key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

## 3. Frontend → Vercel

- **Import** the repo, set **Root Directory = `frontend`** (Vercel auto-detects Vite;
  `vercel.json` handles SPA routing).
- **Environment Variables:**
  | Key | Value |
  |---|---|
  | `VITE_API_BASE_URL` | your backend URL, e.g. `https://pulse-api.onrender.com` |
  | `VITE_SUPABASE_URL` | `https://<ref>.supabase.co` |
  | `VITE_SUPABASE_ANON_KEY` | Supabase anon key |
- These bake in at build time — redeploy after changing them. Never put secrets
  (service-role key, DB url) in `VITE_*`; they ship in the browser bundle.

## 4. Wire the origins together

After the frontend is live, set the backend's `EXTRA_CORS_ORIGINS` to the Vercel
domain (comma-separated for multiple), and add that domain to Supabase Auth's
redirect allow-list. Done.
