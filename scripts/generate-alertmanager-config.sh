#!/usr/bin/env bash
# Generate Alertmanager config from template, substituting env vars.
# Run automatically by manage.sh before compose up.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${1:-$PROJECT_ROOT/.env}"

# Read a single KEY=VALUE line from the env file safely.
# Falls back to the current environment value or an empty string.
read_env() {
  local key="$1"
  local value=""
  if [ -f "$ENV_FILE" ]; then
    value="$(grep "^${key}=" "$ENV_FILE" | tail -n1 | cut -d= -f2-)"
  fi
  printf '%s' "$value"
}

# Resolve a value: environment variable wins, then env file, then default.
resolve() {
  local key="$1"
  local default_value="$2"
  local env_value=""
  env_value="$(read_env "$key")"
  printf '%s' "${!key:-${env_value:-$default_value}}"
}

export SMTP_HOST="$(resolve SMTP_HOST localhost)"
export SMTP_PORT="$(resolve SMTP_PORT 587)"
export SMTP_USER="$(resolve SMTP_USER '')"
export SMTP_PASSWORD="$(resolve SMTP_PASSWORD '')"
# Alertmanager uses SMTP_REQUIRE_TLS; fall back to SMTP_TLS for convenience.
_smtp_tls="$(resolve SMTP_TLS true)"
export SMTP_REQUIRE_TLS="$(resolve SMTP_REQUIRE_TLS $_smtp_tls)"
export ALERTMANAGER_FROM="$(resolve ALERTMANAGER_FROM alerts@nukelab.local)"
export ALERTMANAGER_EMAIL_TO="$(resolve ALERTMANAGER_EMAIL_TO admin@nukelab.local)"
export ALERTMANAGER_WEBHOOK_URL="$(resolve ALERTMANAGER_WEBHOOK_URL http://localhost:5001/webhook)"
export ALERTMANAGER_DEADMAN_URL="$(resolve ALERTMANAGER_DEADMAN_URL http://localhost:5001/deadman)"

mkdir -p "$PROJECT_ROOT/monitoring/alertmanager"

if ! command -v envsubst >/dev/null 2>&1; then
  echo "envsubst not found. Install gettext or add it to the PATH." >&2
  exit 1
fi

envsubst < "$PROJECT_ROOT/monitoring/alertmanager/alertmanager.yml.tpl" \
  > "$PROJECT_ROOT/monitoring/alertmanager/alertmanager.generated.yml"

# If no SMTP user is configured, drop the auth lines so Alertmanager does not
# try to authenticate against a local/open relay.
if [ -z "$SMTP_USER" ]; then
  sed -i '/^  smtp_auth_username:/d; /^  smtp_auth_password:/d' \
    "$PROJECT_ROOT/monitoring/alertmanager/alertmanager.generated.yml"
fi

echo "Generated $PROJECT_ROOT/monitoring/alertmanager/alertmanager.generated.yml"
