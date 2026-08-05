#!/usr/bin/env bash
# Sync the backend's sensitive settings from the repo-root .env into AWS SSM
# Parameter Store as SecureStrings under /pulse/<KEY>. App Runner injects them
# at runtime (see infra/aws/README.md). Re-run after changing any of them,
# then trigger a new App Runner deployment to pick them up.
set -euo pipefail

ENV_FILE="$(dirname "$0")/../../.env"
SECRET_KEYS=(
  DATABASE_URL
  SUPABASE_URL
  SUPABASE_ANON_KEY
  SUPABASE_JWT_SECRET
  SUPABASE_SERVICE_ROLE_KEY
  FERNET_KEY
  TOKEN_ROUTER_API_KEY
  GOOGLE_MAPS_SERVER_API_KEY
  PERPLEXITY_API_KEY
  TOKENMART_API_KEY
  FOURSQUARE_API_KEY
  TAVILY_API_KEY
  EXA_API_KEY
  FIRECRAWL_API_KEY
  SQUARE_APP_ID
  SQUARE_APP_SECRET
  STRIPE_CONNECT_CLIENT_ID
  STRIPE_SECRET_KEY
  RB2B_WEBHOOK_SECRET
  VISITOR_ADMIN_EMAILS
  DISCORD_APPLICATION_ID
  DISCORD_PUBLIC_KEY
  DISCORD_BOT_TOKEN
  DISCORD_GUILD_ID
  DISCORD_ALERT_CHANNEL_ID
  DISCORD_WEBHOOK_URL
  DISCORD_ALLOWED_ROLE_IDS
)

for key in "${SECRET_KEYS[@]}"; do
  # Strip a trailing \r defensively — a CRLF-saved .env would otherwise smuggle
  # a control character into the SSM value and break anything that parses it
  # as a URL/host (e.g. urllib rejects "host.co\r" outright).
  value="$(grep -m1 "^${key}=" "$ENV_FILE" | cut -d= -f2- | tr -d '\r' || true)"
  if [[ -z "$value" ]]; then
    echo "SKIP  $key (not set in .env)"
    continue
  fi
  aws ssm put-parameter \
    --name "/pulse/${key}" \
    --type SecureString \
    --value "$value" \
    --overwrite >/dev/null
  echo "OK    /pulse/${key}"
done
