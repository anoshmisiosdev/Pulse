# Going live — what still needs you

Everything in this document is work I could not verify alone, because it needs
credentials, a domain, or a publicly reachable URL. Everything *not* in this
document is built, tested, and verified end to end against a running server.

Ordered by what blocks the Definition of Done soonest.

---

## 0. Fix these in your current `.env` first

Found while debugging why Stripe and Square "weren't working":

- **`STRIPE_SECRET_KEY` holds a publishable key** (`pk_test_…`). Server calls
  need the *secret* key (`sk_test_…`, Stripe Dashboard → Developers → API keys
  → reveal "Secret key"). The app now detects this, treats billing and "Connect
  with Stripe" as not configured, and logs exactly this at startup — but it
  can't do anything until the right key is in place.
- **`API_BASE_URL` points at `https://api.riyanshomelab.com/`, which isn't
  responding.** Both OAuth callbacks are built from it, so Square and Stripe
  were redirecting you to a dead server after consent. For local testing,
  override it in the backend terminal: `$env:API_BASE_URL = "http://localhost:8000"`.
- **Square's sandbox page hung because of a bug on our side**, now fixed: we
  sent `session=false`, which Square's sandbox doesn't support. Two more
  requirements from Square's docs for sandbox OAuth:
  1. Register `http://localhost:8000/api/integrations/oauth/square/callback` in
     the Developer Console → your app → **OAuth → Sandbox** tab (sandbox allows
     http/localhost; production requires https).
  2. Before clicking "Connect Square", open the **Sandbox Seller Dashboard**
     for a test account (Developer Console → Sandbox test accounts → Open) in
     the same browser. Square requires an active sandbox seller session.
- `STRIPE_WEBHOOK_SECRET` and the three `STRIPE_PRICE_*` values aren't set yet;
  see section 1.

---

## 1. Stripe — blocks "pay $199/mo"

**Why I couldn't finish it:** Checkout and the subscription webhook need a real
Stripe account and a public HTTPS endpoint Stripe can reach. I wrote the full
code path and tested it with literal event payloads (`tests/test_billing.py`,
56 tests), but no card has ever been charged by this code.

**What to do:**

1. In the Stripe Dashboard, create three recurring products and copy the
   **price** ids (`price_…`, not `prod_…`) into `.env`:
   `STRIPE_PRICE_STARTER`, `STRIPE_PRICE_GROWTH`, `STRIPE_PRICE_PRO`.
   Optionally add annual prices at 10× monthly (two months free) in
   `STRIPE_PRICE_*_ANNUAL`.
2. Set `STRIPE_SECRET_KEY`.
3. Register a webhook endpoint at `{API_BASE_URL}/api/billing/webhook` and put
   its signing secret in `STRIPE_WEBHOOK_SECRET`. Subscribe to exactly:
   - `checkout.session.completed`
   - `customer.subscription.created`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.paid`
   - `invoice.payment_failed`

   **This must be a different signing secret from `STRIPE_CONNECT_WEBHOOK_SECRET`.**
   That one verifies a *tenant's* connected account (their customers' charges,
   which we ingest as retention data). This one verifies *our* subscription
   events. They are two trust domains; sharing a secret would let one forge the
   other.
4. For the `founders_rate` discount in the pricing table, create a **promotion
   code** attached to the coupon, not just the coupon. The API deliberately
   does not accept a coupon id from the client — a bare coupon id carries no
   redemption limit or expiry, so accepting one let any tenant apply any coupon
   in the account. Stripe's hosted page shows a promo-code box and enforces
   eligibility itself.
5. Set `BILLING_RETURN_BASE_URL` if the app is served from a different host
   than `FRONTEND_ORIGIN`.

**Verify:** `GET /api/billing/plans` should list your three tiers with real
prices. Then run a test-mode checkout and confirm `GET /api/billing/subscription`
flips to `active` with the right tier. Use `stripe listen --forward-to` for
local webhook testing.

**Until then:** the product works fine. Checkout returns a 503 with "Billing
isn't configured yet", and the UI shows that instead of a dead button.

---

## 2. Resend — blocks "see it send" and the weekly digest

**Why I couldn't finish it:** sending email needs a verified sender domain. The
send path is exercised end to end with the provider mocked; with no key
configured it degrades correctly (`failure_reason: "resend_not_configured"` on
the send row rather than a crash).

**What to do:**

1. Verify your sending domain in Resend, set `RESEND_API_KEY` and
   `RESEND_FROM_EMAIL`.
2. Register the Resend webhook and set `RESEND_WEBHOOK_SECRET` so opens,
   clicks, bounces and complaints come back (this is what makes the campaign
   open/click counts real).
3. Turn on the weekly digest with `DIGEST_ENABLED=true`. It is off by default
   because it sends real email. It goes only to addresses in the `users` table
   with `role='owner'` — never to customers — and a week with nothing to report
   sends nothing at all.

**Verify:** build a campaign, approve it, confirm the send row goes to `sent`
with a `provider_message_id`. Then `POST /api/insights/digest/send` and check
your inbox. `GET /api/insights/digest` previews without sending.

**One thing to check yourself:** the unsubscribe link in generated emails
points at `{API_BASE_URL}/api/automations/unsubscribe`. Confirm that resolves
publicly from a real inbox — CAN-SPAM compliance depends on it and I can't test
it without a public host.

---

## 3. Twilio — blocks SMS (Growth tier)

1. Set `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`.
2. Point the number's inbound webhook at `/api/automations/twilio/inbound` and
   its status callback at `/api/automations/twilio/status`.

**Verify the STOP path specifically.** Text `STOP` to the number from a real
phone and confirm the customer's `unsubscribed_sms` flips. TCPA quiet hours
(no sending before 9am or after 8pm in the business's local timezone) are
enforced in `services/compliance.py` and unit-tested, but the STOP round trip
crosses Twilio and I could not exercise it.

---

## 4. Square OAuth — blocks the one-click integration

Set `SQUARE_APP_ID`, `SQUARE_APP_SECRET`, `SQUARE_ENVIRONMENT`, and register
the redirect URL `{API_BASE_URL}/api/integrations/oauth/square/callback` (see
section 0 for the sandbox specifics).
`SQUARE_WEBHOOK_URL` must match the registered notification URL **exactly** —
it is part of Square's HMAC signature input, so a trailing-slash mismatch
silently fails every webhook.

---

## 5. Bedrock or an Anthropic key — the AI copy and the assistant

The LLM layer (`core/llm.py`) tries AWS Bedrock, then Token Router, then
Anthropic directly. With none configured, everything still works but degrades
visibly:

- campaign copy falls back to a static template (`generated_by: "fallback"`),
- the assistant answers from `chat/intents.py`, a pure keyword matcher, and
  labels itself "reduced mode" in the UI.

That degradation is deliberate and tested — but you are not seeing the real
product until credentials are set. Either give the task role
`bedrock:InvokeModel` and `bedrock:Converse` in `BEDROCK_REGION`, or set
`ANTHROPIC_API_KEY`.

Note the RAG retrieval path needs Bedrock specifically (Cohere embeddings via
`bedrock_embedding_model`) plus `pgvector` on the database. Without it,
retrieval returns no context and generation proceeds ungrounded.

---

## 6. The database migrations — need a real Postgres

Two new revisions on this branch:

- `20261021_0009` — `generation_logs`, `audit_logs`, `chat_conversations`,
  `chat_messages`; columns `campaigns.ab_test`, `campaigns.variant_b_incentive`,
  `campaign_sends.variant`.
- `20261022_0010` — `team_invites`, `webhook_endpoints`, `webhook_deliveries`;
  columns `visits.location`, `transactions.location`, `campaigns.kind`, and four
  review-request columns on `businesses`.

**The app will error on any existing database until these run** —
`create_all` on startup creates missing tables but never adds columns to
existing ones. That's what broke a local dev `local.db` created before these
landed.

**I verified both only in offline mode** (`alembic upgrade --sql`, both upgrade
and downgrade emit complete, correctly ordered SQL). I could not run it against
Postgres: there is no Docker daemon on this machine, and the migration chain
can't run on SQLite because earlier revisions issue pgvector
`CREATE EXTENSION`.

**Please run `alembic upgrade head` against a staging copy of `pulse-db`
before production.** The migration adopts databases that already picked these
tables up via `create_all`, so it is safe to re-run, but that path is untested
on real Postgres.

---

## 7. Built since the first handoff — what each needs from you

- **Team invites + staff role.** Works now; invite links are shown to copy.
  Once Resend is configured (section 2) they're emailed automatically. Staff
  can't touch billing, data export/deletion, team management, review settings
  or webhooks.
- **Multi-location (Pro).** Square supplies locations automatically. CSV users
  need a `location` (or store/branch/studio) column.
- **Outbound webhooks.** Needs the Celery worker + beat running in production
  (`deliver_webhooks_tick`, every minute). Internal/private URLs are refused by
  design, including in development, so test against a public catcher.
- **Review requests.** Off by default. Needs the Celery `queue_review_requests_tick`
  (hourly) and, to actually send, Resend or Twilio.

## 8. Still not built

- **Mindbody** remains a `NotImplementedError` stub, per CLAUDE.md — needs
  Mindbody API credentials to build against.
- **Sentry** — needs your project's DSN.

---

## Current state

- Backend: **779 tests passing**, 1 skipped. `ruff` clean.
- Frontend: **103 tests passing**. `tsc` clean. `vite build` clean.
- Verified end to end against a running server on a clean database: CSV import
  → 50 scored customers → segment → campaign queued (sending nothing) → edit
  → approve → generation and audit logs → assistant answering from real rows
  → digest → CSV and JSON export. A second live run covered locations (Pro
  gate, per-location rollup, segment filter), team invites (hashed token,
  email binding, revoke), webhooks (plan gate, four SSRF targets refused, a
  real delivery attempt recorded) and review requests (drafted once, never
  twice, held for approval).

A security review of this branch found and fixed three issues (unauthorized
Stripe coupon application, entitlement gates ignoring subscription status, and
CSV formula injection in the new export). Tenant isolation, SQL injection,
webhook signature verification, auth bypass and data exposure came back clean.
