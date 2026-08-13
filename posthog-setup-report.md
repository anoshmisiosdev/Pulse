# PostHog post-wizard report

PostHog is integrated into Pulse's FastAPI backend through a failure-isolated client module (`backend/app/core/posthog_client.py`) using the PostHog 7.x instance API with `enable_exception_autocapture=True`. It initializes during the FastAPI lifespan and shuts down gracefully after flushing queued events. Three settings (`POSTHOG_PROJECT_TOKEN`, `POSTHOG_HOST`, `POSTHOG_DISABLED`) are available through Pydantic settings and documented in `.env.example`. Eleven product events cover the onboarding → connect → generate → approve journey, and nine PII-free landing events cover the acquisition → waitlist funnel. A persistent anonymous browser ID is passed to the backend and aliased to the authenticated user so funnel steps remain attributable across sign-in.

| Event | Description | File |
|---|---|---|
| `csv_previewed` | User uploaded a CSV and saw their at-risk customers (top of onboarding funnel). | `backend/app/api/integrations.py` |
| `demo_viewed` | User triggered the instant demo to see scored customers without uploading data. | `backend/app/api/integrations.py` |
| `oauth_flow_started` | User initiated an OAuth flow to connect Square or Stripe. | `backend/app/api/integrations.py` |
| `integration_connected` | User successfully connected a data source (Stripe or Square) via API key. | `backend/app/api/integrations.py` |
| `oauth_connected` | User completed an OAuth connection and data was ingested successfully. | `backend/app/api/integrations.py` |
| `csv_imported` | User imported a CSV into their account (data persisted to database). | `backend/app/api/integrations.py` |
| `data_synced` | User manually triggered a re-sync from all connected live providers. | `backend/app/api/integrations.py` |
| `campaign_generated` | AI generated win-back email or SMS copy for an at-risk customer. | `backend/app/api/campaigns.py` |
| `campaign_approved` | Owner approved a pending campaign send, dispatching email or SMS to the customer. | `backend/app/api/automations.py` |
| `automation_rule_created` | Owner created a new automation rule targeting a churn-risk band. | `backend/app/api/automations.py` |
| `automation_dispatched` | Owner manually triggered the rule engine to evaluate and queue campaigns. | `backend/app/api/automations.py` |

### Landing-page funnel

The browser sends allow-listed events to `POST /api/analytics/landing`; the PostHog project token remains server-side. The endpoint rejects undeclared fields, including form names and email addresses, and is rate-limited to 60 events per minute per IP. The final conversion is emitted by the waitlist API only after the database commit succeeds.

| Event | Description |
|---|---|
| `landing_viewed` | Landing page loaded, with bounded UTM values and referrer host only. |
| `landing_section_viewed` | Visitor reached the demo, pricing, or waitlist section. |
| `landing_cta_clicked` | Visitor clicked a waitlist, live-demo, or sign-in CTA, segmented by placement and pricing plan. |
| `landing_demo_interacted` | Visitor changed the demo vertical or risk slider, reported as a risk band rather than noisy raw values. |
| `landing_waitlist_started` | Visitor first focused the waitlist form. |
| `landing_waitlist_submitted` | A valid, non-honeypot submission reached the waitlist API. |
| `landing_waitlist_validation_failed` | Client validation stopped submission, bucketed by safe reason. |
| `landing_waitlist_submit_failed` | The waitlist request failed. No raw error or form value is sent. |
| `landing_waitlist_joined` | Database-confirmed new or repeat waitlist signup. |

## Next steps

We've built some insights and a dashboard for you to keep an eye on user behavior, based on the events we just instrumented:

- [Analytics basics (wizard) — Dashboard](https://us.posthog.com/project/534290/dashboard/1926585)
- [Onboarding funnel (wizard)](https://us.posthog.com/project/534290/insights/59bwJo2c)
- [Campaigns generated over time (wizard)](https://us.posthog.com/project/534290/insights/EKBmDtaS)
- [Integration connections by provider (wizard)](https://us.posthog.com/project/534290/insights/ltR7vtRp)
- [Campaign approval rate (wizard)](https://us.posthog.com/project/534290/insights/D08uKdpU)
- [Automation rules created (wizard)](https://us.posthog.com/project/534290/insights/nomcLP8y)

## Verify before merging

- [x] Run a full production build and fix lint or type errors introduced by the integration.
- [x] Run the backend and frontend test suites, including focused PostHog regression coverage.
- [x] Add `POSTHOG_PROJECT_TOKEN`, `POSTHOG_HOST`, and `POSTHOG_DISABLED` to `.env.example` and deployment configuration.
- [x] Identify returning visitors through `/api/auth/me` and alias their persistent anonymous browser ID to the authenticated user ID.
- [ ] This project contains data sources PostHog can import (PostgreSQL/Supabase, Stripe, Resend, Square, Twilio, Anthropic). Run `npx @posthog/wizard warehouse` to connect them to PostHog's data warehouse for deeper cross-source analytics.

### Agent skill

We've left an agent skill folder in your project. You can use this context for further agent development when using Claude Code. This will help ensure the model provides the most up-to-date approaches for integrating PostHog.
