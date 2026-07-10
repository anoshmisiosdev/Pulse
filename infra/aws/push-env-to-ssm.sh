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
  SQUARE_APP_ID
  SQUARE_APP_SECRET
  STRIPE_CONNECT_CLIENT_ID
  STRIPE_SECRET_KEY
)

for key in "${SECRET_KEYS[@]}"; do
  value="$(grep -m1 "^${key}=" "$ENV_FILE" | cut -d= -f2- || true)"
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
