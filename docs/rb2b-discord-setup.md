# RB2B + Discord activation

The application code is designed so provider credentials never enter the
browser except for RB2B's public tracking ID. Do not commit bot tokens, webhook
URLs, or the RB2B webhook secret.

## 1. Confirm the public hosts

Before turning on identity resolution, confirm:

- the public marketing-site domain;
- the public API base URL;
- that the privacy mailbox in `/privacy` is monitored; and
- that the API health check and visitor-intelligence migration are live.

RB2B authorizes tracking by domain. The Vercel preview domain can be used for a
private test, but production should use the final marketing domain.

## 2. Activate RB2B

1. In [RB2B Script Setup](https://app.rb2b.com/script), authorize the marketing
   domain and copy the tracking ID.
2. Add the ID to the frontend deployment as `VITE_RB2B_KEY`.
   If the account's copied snippet uses RB2B's CloudFront URL, also set
   `VITE_RB2B_SCRIPT_URL` to
   `https://ddwl4m2hdecbv.cloudfront.net/b/{key}/{key}.js.gz`.
3. Generate a random backend secret and store it as `RB2B_WEBHOOK_SECRET`.
4. Configure RB2B's webhook integration with:

   `https://<api-host>/api/visitors/webhooks/rb2b?key=<RB2B_WEBHOOK_SECRET>`

5. Enable company-only records if they are useful. Enable repeat visits if the
   team wants page-return alerts; Churnary deduplicates identical deliveries.
6. Use RB2B's **Send Test Event** action and confirm the delivery appears under
   Recent Visitors.

The tracking script only loads on the marketing page after analytics consent.
Global Privacy Control disables it. RB2B payloads are mapped and minimized on
the backend, and identifiers used for stitching are hashed.

## 3. Create the Discord application

In the [Discord Developer Portal](https://discord.com/developers/applications):

1. Create an application named `Churnary Visitor Signals`.
2. On **General Information**, copy the Application ID and Public Key.
3. On **Bot**, create/reset the bot token and copy it once.
4. In Discord, enable Developer Mode, then copy the target Server ID and alert
   Channel ID.
5. Store:

   - `DISCORD_APPLICATION_ID`
   - `DISCORD_PUBLIC_KEY`
   - `DISCORD_BOT_TOKEN`
   - `DISCORD_GUILD_ID`
   - `DISCORD_ALERT_CHANNEL_ID`

An incoming channel webhook can replace bot-based alert delivery by setting
`DISCORD_WEBHOOK_URL`. Slash commands still use the Discord application and
signed interactions endpoint.

## 4. Connect and register the bot

1. Set the application's Interactions Endpoint URL to:

   `https://<api-host>/api/discord/interactions`

2. From `backend/`, register the guild commands:

   `uv run python scripts/register_discord_commands.py`

3. Open the install URL printed by the script and add the app to the configured
   server.
4. Use `/churnary status`, `/churnary summary`, and `/churnary recent`.

Commands are ephemeral and default to members with **Manage Server**. To allow
specific non-manager roles, set their comma-separated IDs in
`DISCORD_ALLOWED_ROLE_IDS`.

## 5. Alert behavior

- New non-duplicate RB2B matches are queued for Discord after database commit.
- `DISCORD_ALERT_MIN_INTENT_SCORE` controls the threshold; default is `25`.
- Business email is excluded by default. Set `DISCORD_INCLUDE_EMAIL=true` only
  after confirming the Discord channel's membership and retention policy.
- Discord failure never makes RB2B retry or reject an otherwise valid identity
  delivery.
- The Recent Visitors page has a safe test-notification action and reports
  whether alerts and slash commands are fully configured.
