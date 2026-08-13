# Stripe + Square payment retention integration

Churnary imports provider customer/payment history into one tenant-scoped model,
then recomputes explainable recency, frequency, monetary, and payment-lifecycle
signals. Stripe and Square data use the same scoring path as CSV data.

## What is implemented

1. OAuth or encrypted manual credentials connect a Stripe or Square merchant.
2. An initial pull imports customers, a configurable two-year Square window,
   and bounded full Stripe charge history.
3. Provider customer IDs are stored in `customer_identities`, so one canonical
   customer can retain both a Stripe ID and a Square ID after email/phone dedupe.
4. Payments are upserted by `(business, provider, provider payment id)` with
   completed, failed, partial-refund, full-refund, pending, and canceled states.
5. Completed net-positive payments count as visits and revenue. A later refund
   updates the original payment and removes its inferred visit.
6. Signed webhooks apply customer/payment lifecycle updates. A Celery task also
   runs an overlapping incremental sync every 15 minutes as a recovery path.
7. Scores expose churn risk, an inverse return-likelihood indicator, expected
   next visit, overdue days, payment issues, confidence, and plain-English reasons.

`return_likelihood` is an explainable `100 - churn_risk` indicator. It is not a
statistically calibrated probability and should not be described as one.

## Safe sample data

There is no appropriate shared database of raw, live Stripe or Square card
histories: those records contain sensitive customer and financial data. Churnary
therefore supports two complementary test paths.

### Public retail transactions

The Setup screen's **CSV → Use UCI public payment sample** action imports a
repository fixture derived from Daqing Chen's
[UCI Online Retail dataset](https://archive.ics.uci.edu/dataset/352/online+retail)
([DOI](https://doi.org/10.24432/C5BW33), CC BY 4.0). The source contains 541,909
line items from a UK non-store retailer. Churnary:

- keeps only rows with a pseudonymous `CustomerID`;
- aggregates line items into invoice-level payments;
- preserves cancellations, favorite products, amounts, and interpurchase gaps;
- selects 60 customers across lapsed, middle, and recent cohorts; and
- shifts the entire history near today at import time so churn scoring is useful.

The bundled subset has 1,510 payments, including 222 cancellation/refund
records. It contains no names, emails, card numbers, or provider credentials.
The values remain in the source dataset's GBP units; this fixture is for product
and model behavior testing, not financial reporting.

To reproduce the fixture from the original workbook and run it through the
same scoring code:

```bash
cd backend
uv run python -m app.scripts.uci_online_retail_demo \
  "/path/to/Online Retail.xlsx" \
  --customers 60 \
  --transactions-per-customer 36 \
  --fixture app/data/samples/uci_online_retail_sample.csv
uv run pytest tests/test_uci_online_retail.py tests/test_uci_sample_api.py
```

See `backend/app/data/samples/README.md` for attribution and transformation
details.

### Provider sandboxes

Use the providers' isolated test systems when validating OAuth, pagination,
webhook signatures, or provider-specific lifecycle behavior:

- [Stripe testing environments and Sandboxes](https://docs.stripe.com/testing-use-cases)
- [Square Sandbox overview](https://developer.squareup.com/docs/devtools/sandbox/overview)
- [Square Sandbox payment tokens](https://developer.squareup.com/docs/devtools/sandbox/payments)

For credential-free local and CI verification, Churnary includes deterministic
Stripe- and Square-shaped histories. They run through the production parsers,
not a separate fake scoring path:

```bash
cd backend
uv run python -m app.scripts.payment_history_demo --provider both --customers 40
uv run pytest tests/test_payment_history_e2e.py
```

## Environment

```dotenv
# Shared retention ingest behavior
PAYMENT_HISTORY_LOOKBACK_DAYS=730
PAYMENT_SYNC_OVERLAP_MINUTES=10
PAYMENT_SYNC_INTERVAL_SECONDS=900

# Stripe Connect (register the callback and webhook URLs below)
STRIPE_CONNECT_CLIENT_ID=ca_...
STRIPE_SECRET_KEY=sk_live_...              # platform OAuth code exchange
STRIPE_CONNECT_WEBHOOK_SECRET=whsec_...

# Square OAuth + webhook verification
SQUARE_APP_ID=sq0idp-...
SQUARE_APP_SECRET=sq0csp-...
SQUARE_ENVIRONMENT=sandbox                 # sandbox | production
SQUARE_WEBHOOK_SIGNATURE_KEY=...
SQUARE_WEBHOOK_URL=https://api.example.com/api/integrations/webhooks/square

# Required for all stored provider credentials
FERNET_KEY=...
API_BASE_URL=https://api.example.com
```

Generate `FERNET_KEY` with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Stripe setup

Register this OAuth redirect URL in Stripe:

```text
https://<api-host>/api/integrations/oauth/stripe/callback
```

Churnary requests read-only access. Stripe documents that explicit `read_only`
OAuth is for Connect Extensions, so register this data-reading product with the
appropriate Stripe Connect integration type. The manual fallback accepts a
restricted merchant key with read access to Account, Customers, Charges, and
Events.

Create a connected-account webhook destination:

```text
https://<api-host>/api/integrations/webhooks/stripe
```

Subscribe to:

```text
customer.created
customer.updated
charge.succeeded
charge.failed
charge.updated
charge.refunded
```

Use the destination's signing secret as `STRIPE_CONNECT_WEBHOOK_SECRET`. Stripe
requires signature verification against the unmodified request body; Churnary
also enforces the five-minute replay window.

## Square setup

Register this OAuth redirect URL:

```text
https://<api-host>/api/integrations/oauth/square/callback
```

The app requests only `CUSTOMERS_READ`, `PAYMENTS_READ`, and
`MERCHANT_PROFILE_READ`. Square OAuth access tokens expire after 30 days;
Churnary encrypts the refresh token and refreshes it on the recommended frequent
cadence before expiry.

Register this notification URL, character-for-character, and put the same value
in `SQUARE_WEBHOOK_URL`:

```text
https://<api-host>/api/integrations/webhooks/square
```

Subscribe to:

```text
customer.created
customer.updated
payment.created
payment.updated
```

Use the subscription signature key as `SQUARE_WEBHOOK_SIGNATURE_KEY`. Square's
signature includes both the exact notification URL and raw request body, so a
trailing slash or HTTP/HTTPS mismatch causes verification to fail.

To populate a Square test account, create customers in API Explorer and make
Sandbox payments with `cnon:card-nonce-ok`. Successful calls appear in the
Sandbox Dashboard and are returned by Churnary's normal `/v2/payments` pull.

## Sync and identity rules

- Initial Square pulls explicitly request `PAYMENT_HISTORY_LOOKBACK_DAYS`; Stripe
  walks Charges until exhaustion or the 10,000-record safety cap.
- Square imports each active merchant location rather than silently limiting the
  account to its default location.
- Subsequent pulls overlap the last successful sync by 10 minutes. Square uses
  `updated_at_begin_time`, which captures delayed payments and refunds.
- Stripe Charges do not expose an updated-time list filter; signed charge
  webhooks are therefore the primary refund/update rail. Incremental pulls also
  replay relevant Stripe Events (available for 30 days) to repair missed webhook
  deliveries, alongside newly created charges.
- Customer resolution priority is provider customer ID, normalized email, then
  normalized phone. Guest payments with an email or phone create a minimal
  canonical customer rather than being silently discarded.
- Payments without a provider customer ID and without email/phone remain
  unassigned because Churnary cannot safely infer a person from card details.
- Raw webhook bodies are not retained. Only a small event-ID ledger is stored for
  replay/idempotency protection.

## Deployment and verification

```bash
cd backend
.venv/bin/alembic upgrade head
.venv/bin/pytest
cd ../frontend
npm run build
npm test -- --run
```

Both the API and Celery worker need the same `DATABASE_URL`, `FERNET_KEY`, and
provider OAuth settings. Keep the worker/beat service running; it performs the
15-minute recovery sync and nightly rescoring.

After connecting a Sandbox merchant:

1. Confirm `/api/integrations/status` shows `active` and a recent timestamp.
2. Create a test customer and multiple payments at varied historical dates.
3. Run `POST /api/integrations/sync` and confirm customers, revenue, last visit,
   expected return, and risk reasons appear.
4. Refund one payment and confirm the webhook changes net spend without creating
   a duplicate visit.
5. Trigger a failed payment and confirm the affected customer's risk reasons show
   `Payment on file failed` until a later successful payment resolves the signal.
