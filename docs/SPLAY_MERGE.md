# Splay → Churnary merge

Splay's features now live inside Churnary as one product. This note records what
was brought across, what deliberately wasn't, and where the seams are.

## Why this was a port, not a merge

The two codebases shared no code and no git history:

| | Churnary (this repo) | Splay |
|---|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0 async | Node 22, TypeScript, no framework |
| Data | PostgreSQL (AWS RDS) | JSON files on disk + Convex blob store |
| Frontend | React 18, Tailwind 4, Vite | React 19, hand-written CSS, Vite |
| Auth | Supabase | Hexclave (hosted) |
| Tenancy | `business_id` column | one directory per team |

A `git merge --allow-unrelated-histories` would have produced two applications in
one folder with two auth systems and two databases. Instead the behaviour was
reimplemented in Churnary's stack, keeping Churnary's UI throughout.

Splay's original history is preserved locally under `refs/splay/*`
(`refs/splay/main` at `86c1379`). It is on no branch and is not pushed, so it
stays inspectable for provenance without affecting the remote:

```bash
git log refs/splay/main            # browse the original history
git show refs/splay/main:apps/api/src/engagement.ts
```

## What came across

### Brand kit — `app/social/brand.py`
Voice (name, tagline, audience, tone, positioning, avoid-list) plus look
(five-colour palette, typography, logo).

**Changed on purpose:** Splay overwrote a single `brand-kit.json`, so the
`brand_kit_version` stamped on each generated post pointed at nothing. Here
every save appends a row to `brand_kit_versions`, and posts carry a real foreign
key — a post can be traced back to the exact kit that wrote it. Version 0 is
never stored; it is the synthetic "not set up yet" default, and `version < 1`
is what blocks generation.

### Company brain — `app/social/brain.py`
Owner-curated facts with a `public_safe` flag that defaults to **false**. The
safety property is one line: anything that builds a prompt calls `list_public()`,
never `list_all()`. The unfiltered read exists only for the management screen.

**Changed on purpose:** Splay had no update path, so flipping the flag meant
delete-and-re-add. Since this is the gate deciding what can be said in public,
it is now reversible without losing the record.

This sits *alongside* Churnary's existing `BusinessKnowledge` pgvector store
rather than replacing it. That one is embedding-backed and feeds win-back email
generation; this one is owner-curated with an explicit publication gate and
feeds outward-facing copy. Merging them would put private notes one retrieval
hop from a public post.

### Engagement inbox — `app/social/inbox.py`, `app/social/inbox_rules.py`
Classify inbound comments (intent, sentiment, priority, risk), draft a reply in
three variants, approve, copy out. Plus the "Today's opportunities" briefing.

The single most surprising finding of the port: **Splay's inbox contained no LLM
at all** — classification is regex and replies are string templates. That is
reproduced exactly in `inbox_rules.py` as pure functions, and it now serves as
the never-fails floor. Claude is asked for a better draft only when it is safe
to ask; any failure falls back to the template. Three invariants are enforced
*before* a prompt is built:

1. a high-risk comment (fraud, legal, refund) never reaches the model — it gets
   the fixed escalation text so a human handles it;
2. spam produces no reply;
3. only `public_safe` records are supplied, and the evidence list names exactly
   what was supplied.

Nothing is ever sent. The product does not claim live LinkedIn or X access, the
UI says so, and the final step is a human pressing "Copy approved reply".

### Recurring campaigns — `app/social/campaigns.py`, `app/social/scheduling.py`
One brief fans out into weekly draft slots. Slots are **derived, never stored**,
so changing the cadence can't leave stale rows behind.

The daylight-saving behaviour is the part worth reading. A campaign posting at
9am local must still post at 9am local after the clocks move, which means the
UTC instant has to shift. Splay solved this with a three-round fixed-point
iteration against `Intl.DateTimeFormat`; Python's `zoneinfo` gets there directly
by doing the arithmetic on naive wall-clock fields and re-localising. Both the
fall-back and spring-forward cases are pinned in
`tests/test_campaign_scheduling.py`, including the ambiguous repeated hour and
the nonexistent hour in the spring-forward gap — cases Splay left undefined.

**Changed on purpose:** regeneration replaces only this campaign's *drafts*.
Splay replaced every post, which could destroy work an owner had already
approved.

### Review queue — `app/social/review.py`, `app/social/editorial.py`
Approve, ask for a rewrite, or reject, with an append-only `post_review_events`
trail that records the copy as it read *before* each decision. Posted and
scheduled items deliberately stay in the queue — it doubles as the record of
what actually went out.

**Changed on purpose:** Splay gated approval on a hardcoded list of
private-equity jargon. The generic equivalent is the brand kit's own `avoid`
list, which is already per-business and owner-editable. Splay's hashtag
auto-repair carried over as-is: when the copy is fine and only the tags are
wrong, fix the tags rather than making a human retype them. Approving over a
blocking error is still possible, but only with a written note, and the note is
stored next to the errors it overrode.

### Publishing — `app/social/publish.py`
Buffer, via one long-lived bearer token and opaque channel ids. A post with its
own `scheduled_for` goes out as `customScheduled`; otherwise `shareNow` or
`addToQueue` depending on mode.

Fail-closed at every step: `confirm` must be literally `true`, the post must be
approved, its campaign must be active, Buffer must be configured, and the copy
must fit the platform. **Publishing is not retried** — a timeout after Buffer
has already accepted the post would, on retry, post it twice, and there is no
un-post.

Pausing a campaign is the kill switch: its posts stay approved and visible but
stop being publishable, with no state to repair on resume. Posts with no
campaign are always eligible.

## What was deliberately left out

**Hexclave** (per instruction). Auth is Supabase, as everywhere else in
Churnary. Splay's seven-permission team RBAC (`read_content`, `write_content`,
`review_content`, `schedule_content`, `publish_content`, `manage_brand`,
`manage_analytics`, plus `team_admin`) has no equivalent yet — every route is
scoped to `business_id` and the signed-in owner can do everything. If you add
teams later, that permission set is the model to copy, but declare the required
permission per endpoint rather than reproducing Splay's regex dispatcher, which
silently defaulted new routes to `write_content`.

**Convex.** Post media is meant to go to S3/CloudFront instead
(`S3_MEDIA_BUCKET`, `MEDIA_PUBLIC_BASE_URL`). The constraint to respect: Buffer
fetches the image at publish time, possibly weeks after scheduling, so the URL
has to outlive the schedule. A short-lived presigned URL will silently break a
post scheduled three weeks out. This is configured but **not yet implemented** —
posts currently publish text-only unless `image_url` is already a public URL.

**The visual renderer.** Splay's deterministic branded compositor is ~1,300
lines of SVG generation plus a 20-check pixel QA suite, all driven by headless
Chromium for text measurement and rasterisation. It produced editorial graphics
for a B2B private-equity audience. Reproducing it would mean adding Playwright
and ~400 MB of Chromium to the image for imagery a coffee shop is unlikely to
want. If it's needed later, use Playwright for Python rather than a pure-Python
SVG rasteriser — the text measurement has to agree with Chromium sub-pixel or
every golden fixture has to be re-blessed.

**TokenMart image/video generation.** Config is carried over; the pipeline is
not wired, because without the compositor a raw generated background isn't
useful on its own.

**Splay's editorial scoring.** The six-dimension scored review, the
ten-dimension content fingerprint, the conceptual and lexical diversity guards,
and the three-angle tournament were all tuned for one company's voice in one
industry. The gates that generalise (avoid-list, hashtag rules, platform length
limits) are in `editorial.py`.

**Job serialisation.** Splay refused any output-mutating request while a
background job ran, because jobs were separate OS processes doing
read-modify-write on the same JSON files. With rows in Postgres that class of
race is gone. Campaign generation currently runs inline in the request; if it
gets slow enough to matter, move it to a Celery task and take a Redis lock
keyed on `business_id` — note Splay's queue was global, which was a limitation
rather than a design goal.

## Environment

Eight live values were carried from Splay's `.env` into this repo's `.env`
(backed up to `.env.env.bak`): the Buffer credentials and channel ids, the
publish mode, and the TokenMart key, media base URL, and model ids. Splay's
`TOKENMART_BASE_URL` was mapped to `TOKENMART_MEDIA_BASE_URL` rather than
overwriting Churnary's same-named variable — Splay used the gateway origin,
Churnary's carries the `/v1` suffix for chat completions.

All the Convex variables were dropped. No Hexclave keys were present locally
(their CLI injects them at dev time), and none were carried across.

`.env.example` documents every new variable.

## Tests

```
backend:   218 passing   (uv run pytest)
frontend:   11 passing   (npm run test)
```

New coverage: `test_inbox_rules.py` (classification, drafting, briefing maths),
`test_campaign_scheduling.py` (DST slot generation), `test_social.py` (services,
including tenant isolation and the public-safe gate), `test_social_api.py`
(routes and serialisation), `frontend/src/lib/social.test.ts`.

The LLM is stubbed to fail across the service tests so the deterministic path —
the one that has to work when the model is unreachable — is what's exercised.
One test covers the Claude path and asserts that private context never reaches
the prompt.
