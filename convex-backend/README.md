# Pulse — Convex auth backend

Convex is the system of record for **users + businesses** (one business = one
tenant). The Pulse FastAPI backend calls these HTTP actions with a shared key to
verify logins; the browser never talks to Convex directly.

## What's here

- `convex/schema.ts` — `businesses` and `users` tables (passwords are PBKDF2-hashed).
- `convex/http.ts` — `POST /auth/login` and `POST /auth/register` HTTP actions,
  guarded by the `x-pulse-key` header (must equal the `PULSE_API_KEY` env var).
- `convex/users.ts`, `convex/businesses.ts` — internal queries/mutations.

## Setup

```bash
cd convex-backend
npm install
npx convex dev          # creates a deployment + convex/_generated, prints your URL
```

1. In the Convex dashboard (Settings → Environment Variables), set:
   ```
   PULSE_API_KEY = <a long random secret>
   ```
2. Put the matching values in the repo-root `.env`:
   ```
   CONVEX_URL=https://<your-deployment>.convex.cloud
   CONVEX_API_KEY=<the same PULSE_API_KEY value>
   ```
   (HTTP actions are served from the `.convex.site` domain — the backend derives
   that from `CONVEX_URL` automatically.)

## Create the first tenant

Registration is operator-only (guarded by the shared key), so it isn't a public
sign-up form. Create an account via the Pulse API:

```bash
curl -X POST http://localhost:8000/api/auth/register \
  -H "X-Admin-Key: $CONVEX_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email":"owner@hayward.coffee","password":"s3cret","business_name":"Hayward Coffee Co."}'
```

That owner can now log in at the Pulse login page and see only their tenant's data.

## Deploy to production

```bash
npx convex deploy
```
