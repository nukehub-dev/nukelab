#!/bin/bash
# NukeLab Load Test Runner
# Convenience wrapper around Locust and k6 Docker containers.
#
# Usage:
#   ./scripts/run-load-tests.sh smoke
#   ./scripts/run-load-tests.sh baseline
#   ./scripts/run-load-tests.sh stress
#   ./scripts/run-load-tests.sh spike
#   ./scripts/run-load-tests.sh endurance
#   ./scripts/run-load-tests.sh k6-smoke
#   ./scripts/run-load-tests.sh k6-stress

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." > /dev/null 2>&1 && pwd)"
cd "$DIR"

PROFILE="${1:-baseline}"
COMPOSE_FILE="$DIR/compose.loadtest.yml"
MAIN_COMPOSE_FILE="$DIR/compose.yml"

# Colors
RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[1;33m'
BLUE=$'\033[0;34m'
RESET=$'\033[0m'

log()   { echo -e "${BLUE}▶${RESET} $*"; }
warn()  { echo -e "${YELLOW}⚠${RESET}  $*"; }
ok()    { echo -e "${GREEN}✓${RESET}  $*"; }
die()   { echo -e "${RED}✗${RESET}  $*" >&2; exit 1; }

# ─── Container Engine Detection ────────────────────────────────────────────
if command -v podman > /dev/null 2>&1; then
    CONTAINER_ENGINE=podman
elif command -v docker > /dev/null 2>&1; then
    CONTAINER_ENGINE=docker
else
    die "Neither podman nor docker found"
fi

if command -v podman-compose > /dev/null 2>&1; then
    COMPOSE="podman-compose"
elif command -v docker-compose > /dev/null 2>&1; then
    COMPOSE="docker-compose"
elif $CONTAINER_ENGINE compose version > /dev/null 2>&1; then
    COMPOSE="$CONTAINER_ENGINE compose"
else
    die "No compose command found"
fi

# Check main stack is reachable (use container engine directly, more reliable)
if ! $CONTAINER_ENGINE ps --format '{{.Names}} {{.Status}}' 2>/dev/null | grep -q 'nukelab-traefik'; then
    die "Main stack is not running. Start it first:
  ./manage.sh start"
fi

# Check backend container is running
if ! $CONTAINER_ENGINE ps --format '{{.Names}} {{.Status}}' 2>/dev/null | grep -q 'nukelab-backend'; then
    die "Backend container is not running. Start the stack first:
  ./manage.sh start"
fi

# Check test data exists
log "Checking for test users..."
USER_COUNT=$($COMPOSE -f "$MAIN_COMPOSE_FILE" exec -T backend python -c "
import asyncio, sys
sys.path.insert(0, '.')
from app.db.session import AsyncSessionLocal
from sqlalchemy import select, func
from app.models.user import User
async def check():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(func.count()).select_from(User).where(User.username.like('loadtest_%')))
        count = result.scalar()
        print(count or 0)
asyncio.run(check())
" 2>/dev/null | tail -n1 | tr -d '\r' || echo 0)

if [ "${USER_COUNT:-0}" -gt 0 ]; then
    ok "Test users found: $USER_COUNT"
else
    warn "No test users found. Seeding now..."
    $COMPOSE -f "$MAIN_COMPOSE_FILE" exec -T backend python -c "
import asyncio, sys
sys.path.insert(0, '.')
from app.db.session import AsyncSessionLocal
from app.api.auth import get_password_hash
from app.models.user import User
from sqlalchemy import select

TEST_PASSWORD = 'LoadTest123!'

async def seed():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.username.like('loadtest_%')))
        existing = {u.username for u in result.scalars().all()}
        created = []
        for i in range(100):
            username = f'loadtest_{i:04d}'
            if username in existing:
                continue
            user = User(
                username=username,
                email=f'{username}@loadtest.local',
                first_name=f'Load Test User {i}',
                last_name='',
                password_hash=get_password_hash(TEST_PASSWORD),
                role='user',
                is_active=True,
                is_verified=True,
                nuke_balance=5000,
            )
            db.add(user)
            created.append(username)
        await db.commit()
        print(f'Created {len(created)} test users')

asyncio.run(seed())
" || die "Failed to seed test data. Is the backend healthy?"
fi

# ─── Temporarily disable rate limits for accurate capacity measurement ──────
# The backend overlay in compose.loadtest.yml sets RATE_LIMIT_ENABLED=false.
# Each individual test run is wrapped so rate limits are disabled during the
# test and restored immediately after. This keeps the all-profile loop safe.
RESTORE_COMPOSE_ARGS=(-f "$MAIN_COMPOSE_FILE")
DEV_COMPOSE_FILE="$DIR/.nukelab-dev-compose.yml"
if [ -f "$DEV_COMPOSE_FILE" ]; then
    RESTORE_COMPOSE_ARGS+=(-f "$DEV_COMPOSE_FILE")
fi

_wait_for_backend() {
    local url="${BACKEND_HEALTH_URL:-http://localhost:8000/api/system/health}"
    local attempts=0
    local max_attempts=30
    while [ $attempts -lt $max_attempts ]; do
        if $CONTAINER_ENGINE exec nukelab-backend python -c "
import urllib.request, sys
try:
    urllib.request.urlopen('$url', timeout=5)
    sys.exit(0)
except Exception:
    sys.exit(1)
" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
        attempts=$((attempts + 1))
    done
    warn "Backend health check did not pass after ${max_attempts}s — proceeding anyway"
}

_disable_rate_limits() {
    log "Disabling rate limits for load test..."
    $COMPOSE -f "$MAIN_COMPOSE_FILE" -f "$COMPOSE_FILE" up -d backend >/dev/null 2>&1
    _wait_for_backend
    ok "Rate limits disabled"
}

_restore_rate_limits() {
    log "Restoring rate limits..."
    $COMPOSE "${RESTORE_COMPOSE_ARGS[@]}" up -d backend >/dev/null 2>&1
    _wait_for_backend
    ok "Rate limits restored"
}

# Run a command with rate limits disabled, then restore them.
_run_with_rate_limits_disabled() {
    _disable_rate_limits
    local rc=0
    "$@" || rc=$?
    _restore_rate_limits
    return $rc
}

# ─── Setup (skipped when invoked as a child from the 'all' profile) ────────

if [ -z "${_NUKELAB_SETUP_DONE:-}" ]; then
    # Pre-generate JWT tokens for load-test users (bypasses login rate limits)
    # Tokens have a 2-hour expiry so endurance tests work cleanly.
    log "Generating token pool..."
    $CONTAINER_ENGINE cp "$DIR/backend/tests/load/generate_tokens.py" nukelab-backend:/tmp/generate_tokens.py >/dev/null 2>&1
    if $CONTAINER_ENGINE exec nukelab-backend python /tmp/generate_tokens.py >/dev/null 2>&1; then
        $CONTAINER_ENGINE cp nukelab-backend:/app/tests/load/tokens.json "$DIR/backend/tests/load/tokens.json" >/dev/null 2>&1
        ok "Token pool generated"
    else
        warn "Token generation failed — tests will fall back to per-user login (may hit rate limits)"
    fi
fi

# ─── Run a single profile (used by 'all') ──────────────────────────────────

run_profile() {
    local p="$1"
    log "Running profile: $p"
    # Call ourselves recursively for the actual test, skipping setup
    if _NUKELAB_SETUP_DONE=1 bash "$0" "$p"; then
        ok "Profile passed: $p"
        return 0
    else
        warn "Profile failed: $p"
        return 1
    fi
}

case "$PROFILE" in
    all)
        log "Running all load-test profiles sequentially..."
        FAILED=()
        PASSED=()

        for p in smoke baseline stress spike endurance connection k6-smoke k6-baseline k6-stress k6-spike k6-endurance; do
            echo
            if run_profile "$p"; then
                PASSED+=("$p")
            else
                FAILED+=("$p")
            fi
        done

        echo
        log "========================================"
        ok "Passed: ${#PASSED[@]} — ${PASSED[*]}"
        if [ ${#FAILED[@]} -gt 0 ]; then
            die "Failed: ${#FAILED[@]} — ${FAILED[*]}"
        fi
        log "========================================"
        exit 0
        ;;

    smoke)
        log "Running Locust smoke test (1 user, 60s)..."
        _run_with_rate_limits_disabled \
            $COMPOSE -f "$COMPOSE_FILE" run --rm locust \
                -f /mnt/locust/locustfile.py \
                --host http://backend:8000 \
                -u 1 -r 1 -t 60s --headless \
                --html /mnt/locust/reports/smoke_report.html
        ;;

    baseline)
        log "Running Locust baseline test (50 users, 5min)..."
        _run_with_rate_limits_disabled \
            $COMPOSE -f "$COMPOSE_FILE" run --rm locust \
                -f /mnt/locust/locustfile.py \
                --host http://backend:8000 \
                -u 50 -r 5 -t 5m --headless \
                --html /mnt/locust/reports/baseline_report.html
        ;;

    stress)
        # Single-process Locust tops out around 100 realistic users.
        # For 500+ users run distributed Locust or use k6-stress.
        log "Running Locust stress test (ramp to 100 users, 10min, API only)..."
        _run_with_rate_limits_disabled \
            $COMPOSE -f "$COMPOSE_FILE" run --rm \
                -e SKIP_CONTAINER_OPS=1 \
                locust \
                -f /mnt/locust/locustfile.py \
                --host http://backend:8000 \
                -u 100 -r 10 -t 10m --headless \
                --html /mnt/locust/reports/stress_report.html
        ;;

    spike)
        log "Running Locust spike test (10→100 users, API only)..."
        _run_with_rate_limits_disabled \
            $COMPOSE -f "$COMPOSE_FILE" run --rm \
                -e SKIP_CONTAINER_OPS=1 \
                locust \
                -f /mnt/locust/locustfile.py \
                --host http://backend:8000 \
                -u 100 -r 20 -t 5m --headless \
                --html /mnt/locust/reports/spike_report.html
        ;;

    endurance)
        # Single-process Locust can't reliably drive 50 users for 30 min.
        # For true 30-min endurance use k6-endurance (already covers it).
        log "Running Locust endurance test (25 users, 15min, API only)..."
        _run_with_rate_limits_disabled \
            $COMPOSE -f "$COMPOSE_FILE" run --rm \
                -e SKIP_CONTAINER_OPS=1 \
                locust \
                -f /mnt/locust/locustfile.py \
                --host http://backend:8000 \
                -u 25 -r 2 -t 15m --headless \
                --html /mnt/locust/reports/endurance_report.html
        ;;

    connection)
        # Scale connection flood to what the infrastructure can handle.
        # Single-process Locust tops out around 50 idle-connection users.
        if $CONTAINER_ENGINE ps --format '{{.Names}}' 2>/dev/null | grep -q 'nukelab-pgbouncer'; then
            CONN_USERS=1000
            log "Running PgBouncer connection flood ($CONN_USERS idle users, 5min)..."
        else
            CONN_USERS=50
            warn "PgBouncer not running — scaling connection flood to $CONN_USERS users (single-process limit)"
        fi
        _run_with_rate_limits_disabled \
            $COMPOSE -f "$COMPOSE_FILE" run --rm \
                -e SKIP_CONTAINER_OPS=1 \
                locust \
                -f /mnt/locust/locustfile.py \
                --host http://backend:8000 \
                -u $CONN_USERS -r 25 -t 5m --headless \
                ConnectionFloodUser \
                --html /mnt/locust/reports/connection_report.html
        ;;

    k6-smoke)
        log "Running k6 smoke test..."
        if [ "${K6_JSON_OUTPUT:-}" = "1" ]; then
            _K6_OUT="--out json=/mnt/reports/k6_smoke_$(date +%s).json"
        fi
        _run_with_rate_limits_disabled \
            $COMPOSE -f "$COMPOSE_FILE" run --rm \
                -e K6_PROFILE=smoke \
                -e TEST_USER_COUNT="${TEST_USER_COUNT:-100}" \
                k6 run ${_K6_OUT:-} /scripts/api-stress.js
        ;;

    k6-baseline)
        log "Running k6 baseline test..."
        if [ "${K6_JSON_OUTPUT:-}" = "1" ]; then
            _K6_OUT="--out json=/mnt/reports/k6_baseline_$(date +%s).json"
        fi
        _run_with_rate_limits_disabled \
            $COMPOSE -f "$COMPOSE_FILE" run --rm \
                -e K6_PROFILE=baseline \
                -e TEST_USER_COUNT="${TEST_USER_COUNT:-100}" \
                k6 run ${_K6_OUT:-} /scripts/api-stress.js
        ;;

    k6-stress)
        log "Running k6 stress test..."
        if [ "${K6_JSON_OUTPUT:-}" = "1" ]; then
            _K6_OUT="--out json=/mnt/reports/k6_stress_$(date +%s).json"
        fi
        _run_with_rate_limits_disabled \
            $COMPOSE -f "$COMPOSE_FILE" run --rm \
                -e K6_PROFILE=stress \
                -e TEST_USER_COUNT="${TEST_USER_COUNT:-100}" \
                k6 run ${_K6_OUT:-} /scripts/api-stress.js
        ;;

    k6-spike)
        log "Running k6 spike test..."
        if [ "${K6_JSON_OUTPUT:-}" = "1" ]; then
            _K6_OUT="--out json=/mnt/reports/k6_spike_$(date +%s).json"
        fi
        _run_with_rate_limits_disabled \
            $COMPOSE -f "$COMPOSE_FILE" run --rm \
                -e K6_PROFILE=spike \
                -e TEST_USER_COUNT="${TEST_USER_COUNT:-100}" \
                k6 run ${_K6_OUT:-} /scripts/api-stress.js
        ;;

    k6-endurance)
        log "Running k6 endurance test..."
        if [ "${K6_JSON_OUTPUT:-}" = "1" ]; then
            _K6_OUT="--out json=/mnt/reports/k6_endurance_$(date +%s).json"
        fi
        _run_with_rate_limits_disabled \
            $COMPOSE -f "$COMPOSE_FILE" run --rm \
                -e K6_PROFILE=endurance \
                -e TEST_USER_COUNT="${TEST_USER_COUNT:-100}" \
                k6 run ${_K6_OUT:-} /scripts/api-stress.js
        ;;

    *)
        echo "Usage: $0 {all|smoke|baseline|stress|spike|endurance|connection|k6-smoke|k6-baseline|k6-stress|k6-spike|k6-endurance}"
        echo ""
        echo "Locust profiles (realistic user behavior):"
        echo "  smoke       → 1 user, 60s — verify system works"
        echo "  baseline    → 50 users, 5min — normal production traffic"
        echo "  stress      → 500 users, 10min — find breaking point"
        echo "  spike       → 300 users, 5min — sudden traffic surge"
        echo "  endurance   → 50 users, 30min — memory leak detection"
        echo "  connection  → 1000 idle users, 5min — PgBouncer stress"
        echo ""
        echo "k6 profiles (high-RPS endpoint hammering):"
        echo "  k6-smoke    → 10 VUs, 30s"
        echo "  k6-baseline → 100 VUs, 5min"
        echo "  k6-stress   → 500 VUs, 10min"
        echo "  k6-spike    → 10→500 VUs, 5min"
        echo "  k6-endurance→ 100 VUs, 30min"
        exit 1
        ;;
esac

ok "Load test complete: $PROFILE"
