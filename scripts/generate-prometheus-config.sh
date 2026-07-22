#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Generate Prometheus config from template, conditionally adding PgBouncer scrape jobs.
# Run automatically by nukelabctl before compose up.

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

_pgbouncer_enabled="$(resolve PGBOUNCER_ENABLED false)"

if [ "$_pgbouncer_enabled" = "true" ]; then
    export PGBOUNCER_SCRAPE_JOBS="  - job_name: 'pgbouncer-exporter'
    static_configs:
      - targets: ['pgbouncer-exporter:9127']"
else
    export PGBOUNCER_SCRAPE_JOBS=""
fi

mkdir -p "$PROJECT_ROOT/monitoring/prometheus"

if ! command -v envsubst > /dev/null 2>&1; then
    echo "envsubst not found. Install gettext or add it to the PATH." >&2
    exit 1
fi

envsubst < "$PROJECT_ROOT/monitoring/prometheus/prometheus.yml.tpl" \
    > "$PROJECT_ROOT/monitoring/prometheus/prometheus.generated.yml"

echo "Generated $PROJECT_ROOT/monitoring/prometheus/prometheus.generated.yml"
