#!/bin/sh
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# NukeLab environment healthcheck.
#
#   1. /health            — nginx itself is accepting connections
#   2. sidecar :8081      — auth sidecar liveness (skipped when auth is off).
#                           Probed DIRECTLY, not through nginx: nginx rewrites
#                           sidecar outages to a 200 starting.html via
#                           error_page, which would mask the failure.
#   3. "$@" and URLs in $NUKELAB_HEALTH_PROBE_URLS (space-separated) —
#                           app probes added by child images via ENV (ttyd,
#                           IDE), also probed directly.
#
# The backend injects this script as the container healthcheck at create
# time (docker_driver.py); HealthCheckService reads State.Health.Status and
# auto-restarts after consecutive failures.

curl -sf --max-time 3 http://localhost:8080/health > /dev/null || exit 1

if [ "${NUKELAB_AUTH_ENABLED:-true}" = "true" ]; then
    auth_port="${NUKELAB_AUTH_LISTEN_ADDR##*:}"
    curl -sf --max-time 3 "http://localhost:${auth_port:-8081}/health" > /dev/null || exit 1
fi

# Word-splitting of NUKELAB_HEALTH_PROBE_URLS is intentional (space-separated).
# shellcheck disable=SC2086
for url in "$@" ${NUKELAB_HEALTH_PROBE_URLS:-}; do
    [ -z "$url" ] && continue
    curl -sf --max-time 3 "$url" > /dev/null || exit 1
done

exit 0
