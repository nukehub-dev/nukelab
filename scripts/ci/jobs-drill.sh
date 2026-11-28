#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Opt-in interruption drill for single-run batch jobs.
#
# Starts or assumes a dedicated disposable stack, submits one real zero-cost
# job, kills the Celery worker (or the Redis broker), restarts it, and proves
# from the database, API and Docker events that the interruption produced
# exactly one job row, one created/started runtime, one terminal result, one
# released volume guard and no duplicate billing/authorization.
#
# This is intentionally not part of the default PR path: it kills worker or
# broker processes and must only run against a dedicated disposable stack.
#
# Usage: scripts/ci/jobs-drill.sh [options]
#
# Options:
#   --dry-run             Validate the engine, stack, login and job gates only.
#   --interrupt worker    Hard-kill and restart celery-worker (default).
#   --interrupt broker    Restart redis, then restart celery-worker.
#   --start               Start an already-built disposable stack and wait.
#   --build               Build the stack images, then start and wait.
#   --stop                Stop the disposable stack after the drill.
#   -h, --help            Show this help.
#
# Environment:
#   BASE_URL                    Stack origin (default: http://127.0.0.1:8080)
#   TEST_ADMIN_USERNAME         Admin login user (default: admin)
#   TEST_ADMIN_PASSWORD         Admin password (default: admin123)
#   E2E_RUNTIME_IMAGE           Seeded local fixture image (default:
#                               nukelab-e2e-runtime:a)
#   CONTAINER_ENGINE            docker (default) or an explicit engine binary
#   JOBS_DRILL_TIMEOUT_SECONDS  Terminal deadline (default: 300)
#   JOBS_DRILL_POLL_SECONDS     Poll interval (default: 1)
#
# Example (disposable host or CI runner):
#   ./scripts/ci/jobs-drill.sh --build --stop

set -euo pipefail
set -E

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" > /dev/null 2>&1 && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." > /dev/null 2>&1 && pwd)"
# DIR is consumed by scripts/lib.sh when it defines shared paths.
# shellcheck disable=SC2034
DIR="$REPO_ROOT"
cd "$REPO_ROOT"

# shellcheck source=scripts/lib.sh
source "$REPO_ROOT/scripts/lib.sh"

BASE_URL="${BASE_URL:-http://127.0.0.1:8080}"
ADMIN_USERNAME="${TEST_ADMIN_USERNAME:-admin}"
ADMIN_PASSWORD="${TEST_ADMIN_PASSWORD:-admin123}"
RUNTIME_IMAGE="${E2E_RUNTIME_IMAGE:-nukelab-e2e-runtime:a}"
DRILL_TIMEOUT_SECONDS="${JOBS_DRILL_TIMEOUT_SECONDS:-300}"
POLL_INTERVAL_SECONDS="${JOBS_DRILL_POLL_SECONDS:-1}"
ENGINE="${CONTAINER_ENGINE:-docker}"

DRY_RUN=false
START_STACK=false
BUILD_STACK=false
STOP_STACK=false
INTERRUPT_TARGET="worker"

TMP_DIR=""
EVENTS_PID=""
EVENTS_FILE=""
ADMIN_TOKEN=""
VOLUME_ID=""
VOLUME_NAME=""
JOB_ID=""
JOB_KEY=""
JOB_BODY=""
CONTAINER_ID=""
PLAN_ID=""
ENVIRONMENT_ID=""
REVISION_ID=""
STAMP=""
PG_USER=""
PG_DB=""
HTTP_STATUS=""
HTTP_BODY=""
SUBMIT_AT_MS=0
RUNNING_AT_MS=0
INTERRUPT_AT_MS=0
TERMINAL_AT_MS=0

usage() {
    cat <<- EOF
${BOLD}Usage:${RESET} scripts/ci/jobs-drill.sh [options]

Run the opt-in batch-job interruption drill against a dedicated disposable stack.

${BOLD}Options:${RESET}
  --dry-run             Validate engine, stack, login and job gates only.
  --interrupt worker    Hard-kill and restart celery-worker (default).
  --interrupt broker    Restart redis, then restart celery-worker.
  --start               Start an already-built disposable stack and wait.
  --build               Build the stack images, then start and wait.
  --stop                Stop the disposable stack after the drill.
  -h, --help            Show this help.

${BOLD}Environment:${RESET}
  BASE_URL                    Stack origin (default: ${BASE_URL})
  TEST_ADMIN_USERNAME         Admin login user (default: ${ADMIN_USERNAME})
  TEST_ADMIN_PASSWORD         Admin password
  E2E_RUNTIME_IMAGE           Seeded local fixture image (default: ${RUNTIME_IMAGE})
  CONTAINER_ENGINE            Engine binary (default: docker)
  JOBS_DRILL_TIMEOUT_SECONDS  Terminal deadline (default: ${DRILL_TIMEOUT_SECONDS})
  JOBS_DRILL_POLL_SECONDS     Poll interval (default: ${POLL_INTERVAL_SECONDS})

${BOLD}Examples:${RESET}
  ./scripts/ci/jobs-drill.sh --build --stop
  ./scripts/ci/jobs-drill.sh --interrupt broker
EOF
}

_cleanup() {
    local status=$?
    set +e
    if [ -n "$EVENTS_PID" ]; then
        kill "$EVENTS_PID" 2> /dev/null || true
        wait "$EVENTS_PID" 2> /dev/null || true
        EVENTS_PID=""
    fi
    if [ "$DRY_RUN" = false ] && [ -n "$ADMIN_TOKEN" ] && [ -n "$JOB_ID" ]; then
        _api GET "/api/jobs/${JOB_ID}" "$ADMIN_TOKEN" || true
        if [ "$HTTP_STATUS" = "200" ]; then
            local job_state=""
            job_state="$(_json_path "$HTTP_BODY" state || true)"
            case "$job_state" in
                queued | starting | running | cancelling)
                    warn "Cancelling drill job ${JOB_ID} during cleanup"
                    _api POST "/api/jobs/${JOB_ID}/cancel" "$ADMIN_TOKEN" "" || true
                    _wait_job_state "succeeded failed cancelled timed_out expired" 90 > /dev/null 2>&1 || true
                    ;;
            esac
        fi
    fi
    if [ "$DRY_RUN" = false ] && [ -n "$VOLUME_ID" ] && [ -n "$ADMIN_TOKEN" ]; then
        _delete_volume || warn "Drill volume ${VOLUME_ID} was not removed; the disposable stack owns it"
    fi
    if [ -n "$TMP_DIR" ] && [ -d "$TMP_DIR" ]; then
        rm -rf "$TMP_DIR"
    fi
    if [ "$STOP_STACK" = true ] && [ "$DRY_RUN" = false ]; then
        ./scripts/ci/e2e-stack.sh stop || warn "Stack stop reported an error"
    fi
    exit "$status"
}

_api() {
    local method="$1"
    local path="$2"
    local token="${3:-}"
    local data="${4:-}"
    local -a args=(--silent --show-error --max-time 60 --request "$method")
    args+=(--header "Accept: application/json")
    if [ -n "$token" ]; then
        args+=(--header "Authorization: Bearer ${token}")
    fi
    if [ -n "$data" ]; then
        args+=(--header "Content-Type: application/json" --data "$data")
    fi
    local response=""
    response="$(curl "${args[@]}" --write-out $'\n%{http_code}' "${BASE_URL}${path}")"
    HTTP_STATUS="${response##*$'\n'}"
    HTTP_BODY="${response%$'\n'*}"
}

_json_path() {
    python3 -c '
import json
import sys

value = json.loads(sys.argv[1])
try:
    for part in sys.argv[2].split("."):
        value = value[part] if isinstance(value, dict) else value[int(part)]
except (KeyError, IndexError, TypeError):
    print("")
    raise SystemExit(0)
if value is None:
    print("")
elif isinstance(value, bool):
    print("true" if value else "false")
else:
    print(value)
' "$1" "$2"
}

_now_ms() {
    date -u +%s%3N
}

_assert_eq() {
    local label="$1"
    local actual="$2"
    local expected="$3"
    if [ "$actual" != "$expected" ]; then
        die "${label}: expected '${expected}', got '${actual}'"
    fi
}

_assert_nonempty() {
    local label="$1"
    local value="$2"
    if [ -z "$value" ]; then
        die "${label}: expected a non-empty value"
    fi
}

_require_engine() {
    if ! command -v "$ENGINE" > /dev/null 2>&1; then
        die "Container engine '${ENGINE}' is not installed"
    fi
    if ! "$ENGINE" version --format '{{.Server.Version}}' > /dev/null 2>&1; then
        die "Container engine '${ENGINE}' is not reachable"
    fi
}

_require_running_container() {
    local name="$1"
    local running=""
    running="$("$ENGINE" inspect --format '{{.State.Running}}' "$name" 2> /dev/null || true)"
    if [ "$running" != "true" ]; then
        die "Container ${name} is not running; start the disposable stack first"
    fi
}

_preflight() {
    step "Preflight"
    _require_engine
    _require_running_container nukelab-postgres
    _require_running_container nukelab-redis
    _require_running_container nukelab-backend
    _require_running_container nukelab-celery-worker
    _require_running_container nukelab-celery-beat

    local login=""
    login="$(
        curl --silent --show-error --max-time 30 \
            --request POST \
            --header 'Content-Type: application/x-www-form-urlencoded' \
            --data-urlencode "username=${ADMIN_USERNAME}" \
            --data-urlencode "password=${ADMIN_PASSWORD}" \
            "${BASE_URL}/api/auth/login"
    )"
    ADMIN_TOKEN="$(_json_path "$login" access_token)"
    _assert_nonempty "admin login" "$ADMIN_TOKEN"

    _api GET "/api/jobs/capabilities" "$ADMIN_TOKEN"
    _assert_eq "job capabilities status" "$HTTP_STATUS" "200"
    _assert_eq "job submission enabled" "$(_json_path "$HTTP_BODY" enabled)" "true"
    _assert_eq "job submission allowed" "$(_json_path "$HTTP_BODY" can_submit)" "true"
    _assert_eq "job billing mode" "$(_json_path "$HTTP_BODY" billing_mode)" "zero_cost"

    PG_USER="$("$ENGINE" exec nukelab-postgres printenv POSTGRES_USER)"
    PG_DB="$("$ENGINE" exec nukelab-postgres printenv POSTGRES_DB)"
    _assert_nonempty "postgres user" "$PG_USER"
    _assert_nonempty "postgres database" "$PG_DB"

    local image_id=""
    image_id="$(image_identity)"
    if [ "$image_id" = "missing" ]; then
        die "Runtime fixture image ${RUNTIME_IMAGE} is not available locally"
    fi
    log "Preflight passed: engine=$("$ENGINE" version --format '{{.Server.Version}}') image=${image_id}"
}

image_identity() {
    "$ENGINE" image inspect --format '{{.Id}}' "$RUNTIME_IMAGE" 2> /dev/null || echo "missing"
}

_seed_fixture() {
    step "Seeding the disposable job fixture"
    local output=""
    output="$(
        "$ENGINE" exec -i \
            -e NUKELAB_JOBS_SEED_ALLOW=1 \
            -e "TEST_ADMIN_USERNAME=${ADMIN_USERNAME}" \
            -e "E2E_RUNTIME_IMAGE=${RUNTIME_IMAGE}" \
            nukelab-backend python - < "$REPO_ROOT/scripts/ci/seed-jobs-fixture.py"
    )"
    _assert_eq "seed result" "$(_json_path "$output" ok)" "true"
    PLAN_ID="$(_json_path "$output" plan_id)"
    ENVIRONMENT_ID="$(_json_path "$output" environment_id)"
    REVISION_ID="$(_json_path "$output" revision_id)"
    _assert_nonempty "seed plan" "$PLAN_ID"
    _assert_nonempty "seed environment" "$ENVIRONMENT_ID"
    _assert_nonempty "seed revision" "$REVISION_ID"
    log "Seeded plan=${PLAN_ID} environment=${ENVIRONMENT_ID} revision=${REVISION_ID}"
}

_create_volume() {
    step "Creating a private drill volume"
    local body=""
    body="$(printf '{"display_name":"Jobs drill %s","description":"Disposable interruption drill volume","max_size_bytes":67108864}' "$STAMP")"
    _api POST "/api/volumes/" "$ADMIN_TOKEN" "$body"
    _assert_eq "volume create status" "$HTTP_STATUS" "201"
    VOLUME_ID="$(_json_path "$HTTP_BODY" id)"
    VOLUME_NAME="$(_json_path "$HTTP_BODY" name)"
    _assert_nonempty "volume id" "$VOLUME_ID"
    _assert_nonempty "volume name" "$VOLUME_NAME"

    "$ENGINE" run --rm --network none --user 0:0 \
        -v "${VOLUME_NAME}:/work" --entrypoint /bin/chmod \
        "$RUNTIME_IMAGE" 0777 /work > /dev/null
    "$ENGINE" run --rm --network none --user 65532:65532 \
        -v "${VOLUME_NAME}:/work" --entrypoint /bin/sh \
        "$RUNTIME_IMAGE" -c "printf 'jobs-drill-input-%s' '${STAMP}' > /work/input.txt" > /dev/null
}

_start_events() {
    EVENTS_FILE="${TMP_DIR}/events.jsonl"
    "$ENGINE" events \
        --filter type=container \
        --filter 'label=nukelab.workload=job' \
        --format '{{json .}}' > "$EVENTS_FILE" 2> /dev/null &
    EVENTS_PID=$!
    sleep 1
    if ! kill -0 "$EVENTS_PID" 2> /dev/null; then
        die "Container event capture did not start"
    fi
}

_submit_job() {
    step "Submitting one real zero-cost job"
    SUBMIT_AT_MS="$(_now_ms)"
    JOB_KEY="jobs-drill-${STAMP}"
    JOB_BODY="$(
        cat <<- EOF
{"name":"jobs-drill-${STAMP}","revision_id":"${REVISION_ID}","plan_id":"${PLAN_ID}","volume_id":"${VOLUME_ID}","argv":["/bin/sh","-c","echo drill-started; sleep 45; printf drill-ok > /work/drill-output.txt"],"max_runtime_seconds":300}
EOF
    )"
    local response=""
    response="$(
        curl --silent --show-error --max-time 60 \
            --request POST \
            --header "Authorization: Bearer ${ADMIN_TOKEN}" \
            --header 'Content-Type: application/json' \
            --header "Idempotency-Key: ${JOB_KEY}" \
            --data "$JOB_BODY" \
            --write-out $'\n%{http_code}' \
            "${BASE_URL}/api/jobs"
    )"
    HTTP_STATUS="${response##*$'\n'}"
    HTTP_BODY="${response%$'\n'*}"
    _assert_eq "job submit status" "$HTTP_STATUS" "202"
    JOB_ID="$(_json_path "$HTTP_BODY" id)"
    _assert_nonempty "job id" "$JOB_ID"
    _assert_eq "submitted job state" "$(_json_path "$HTTP_BODY" state)" "queued"
    log "Submitted job ${JOB_ID}"
}

_wait_job_state() {
    local wanted="$1"
    local timeout="${2:-$DRILL_TIMEOUT_SECONDS}"
    local deadline=$((SECONDS + timeout))
    local job_state=""
    while [ "$SECONDS" -lt "$deadline" ]; do
        _api GET "/api/jobs/${JOB_ID}" "$ADMIN_TOKEN"
        if [ "$HTTP_STATUS" = "200" ]; then
            job_state="$(_json_path "$HTTP_BODY" state)"
            case " ${wanted} " in
                *" ${job_state} "*)
                    return 0
                    ;;
            esac
            case "$job_state" in
                failed | cancelled | timed_out | expired | recovery_required)
                    return 1
                    ;;
            esac
        fi
        sleep "$POLL_INTERVAL_SECONDS"
    done
    return 1
}

_wait_container_running() {
    local name="$1"
    local deadline=$((SECONDS + 120))
    local running=""
    while [ "$SECONDS" -lt "$deadline" ]; do
        running="$("$ENGINE" inspect --format '{{.State.Running}}' "$name" 2> /dev/null || true)"
        if [ "$running" = "true" ]; then
            return 0
        fi
        sleep 1
    done
    return 1
}

_wait_redis_ready() {
    local deadline=$((SECONDS + 120))
    while [ "$SECONDS" -lt "$deadline" ]; do
        if "$ENGINE" exec nukelab-redis redis-cli ping 2> /dev/null | grep -q PONG; then
            return 0
        fi
        sleep 1
    done
    return 1
}

_find_job_container() {
    local -a ids=()
    local id=""
    while IFS= read -r id; do
        [ -n "$id" ] && ids+=("$id")
    done < <(
        "$ENGINE" ps -a --no-trunc \
            --filter "label=nukelab.job.id=${JOB_ID}" \
            --format '{{.ID}}'
    )
    if [ ${#ids[@]} -ne 1 ]; then
        die "Expected exactly one workload container for job ${JOB_ID}, found ${#ids[@]}"
    fi
    CONTAINER_ID="${ids[0]}"
}

_interrupt() {
    step "Interrupting ${INTERRUPT_TARGET} while the job is running"
    INTERRUPT_AT_MS="$(_now_ms)"
    case "$INTERRUPT_TARGET" in
        worker)
            "$ENGINE" kill nukelab-celery-worker > /dev/null
            sleep 2
            "$ENGINE" start nukelab-celery-worker > /dev/null 2>&1 || true
            _wait_container_running nukelab-celery-worker \
                || die "celery-worker did not restart"
            ;;
        broker)
            "$ENGINE" restart --time 1 nukelab-redis > /dev/null
            _wait_redis_ready || die "redis did not become ready after restart"
            "$ENGINE" restart --time 1 nukelab-celery-worker > /dev/null
            _wait_container_running nukelab-celery-worker \
                || die "celery-worker did not reconnect after the broker restart"
            ;;
        *)
            die "Unsupported interrupt target: ${INTERRUPT_TARGET}"
            ;;
    esac
    log "Restarted ${INTERRUPT_TARGET}; waiting for the durable monitor to settle the job"
}

_db_scalar() {
    "$ENGINE" exec nukelab-postgres \
        psql -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 -tAc "$1"
}

_wait_cleanup() {
    local deadline=$((SECONDS + 90))
    local cleanup=""
    while [ "$SECONDS" -lt "$deadline" ]; do
        cleanup="$(_db_scalar "SELECT cleanup_state FROM batch_jobs WHERE id = '${JOB_ID}'")"
        if [ "$cleanup" = "complete" ]; then
            return 0
        fi
        sleep 1
    done
    return 1
}

_events_summary() {
    python3 - "$EVENTS_FILE" "$JOB_ID" << 'PY'
import json
import sys

path, job_id = sys.argv[1], sys.argv[2]
create_ids = set()
start_ids = set()
die = 0
destroy = 0
with open(path, encoding="utf-8") as handle:
    for line in handle:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        actor = event.get("Actor") or {}
        attributes = actor.get("Attributes") or {}
        event_job_id = attributes.get("nukelab.job.id")
        if not event_job_id:
            name = (attributes.get("name") or "").lstrip("/")
            prefix = "nukelab-job-"
            if name.startswith(prefix):
                event_job_id = name[len(prefix) :]
        if event_job_id != job_id:
            continue
        action = event.get("Action")
        actor_id = actor.get("ID")
        if action == "create":
            create_ids.add(actor_id)
        elif action == "start":
            start_ids.add(actor_id)
        elif action == "die":
            die += 1
        elif action == "destroy":
            destroy += 1
print(
    json.dumps(
        {
            "create": len(create_ids),
            "start": len(start_ids),
            "die": die,
            "destroy": destroy,
            "create_ids": sorted(value for value in create_ids if value),
            "start_ids": sorted(value for value in start_ids if value),
        },
        sort_keys=True,
    )
)
PY
}

_delete_volume() {
    local deadline=$((SECONDS + 60))
    while [ "$SECONDS" -lt "$deadline" ]; do
        _api DELETE "/api/volumes/${VOLUME_ID}" "$ADMIN_TOKEN"
        case "$HTTP_STATUS" in
            200 | 204 | 404)
                VOLUME_ID=""
                return 0
                ;;
            409 | 400)
                sleep 2
                ;;
            *)
                return 1
                ;;
        esac
    done
    return 1
}

_evidence() {
    python3 - "$@" << 'PY'
import json
import sys

payload = {}
for item in sys.argv[1:]:
    key, _, value = item.partition("=")
    payload[key] = value
print(json.dumps(payload, sort_keys=True))
PY
}

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --interrupt)
            [ $# -ge 2 ] || die "Missing value for --interrupt"
            INTERRUPT_TARGET="$2"
            shift 2
            ;;
        --start)
            START_STACK=true
            shift
            ;;
        --build)
            BUILD_STACK=true
            START_STACK=true
            shift
            ;;
        --stop)
            STOP_STACK=true
            shift
            ;;
        -h | --help | help)
            usage
            exit 0
            ;;
        *)
            die "Unknown option: $1\nRun '$0 --help' for usage."
            ;;
    esac
done

case "$INTERRUPT_TARGET" in
    worker | broker) ;;
    *) die "Unsupported --interrupt value: ${INTERRUPT_TARGET}" ;;
esac

trap _cleanup EXIT
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/nukelab-jobs-drill.XXXXXX")"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)-$$"

if [ "$BUILD_STACK" = true ]; then
    step "Building the disposable stack"
    ./scripts/ci/e2e-stack.sh build
fi
if [ "$START_STACK" = true ]; then
    step "Starting the disposable stack"
    ./scripts/ci/e2e-stack.sh start
    ./scripts/ci/e2e-stack.sh wait
fi

_preflight

if [ "$DRY_RUN" = true ]; then
    log "Dry run: would seed the fixture, create a private volume, submit one job, interrupt ${INTERRUPT_TARGET}, and assert one result/guard."
    _evidence \
        "scope=jobs-drill-preflight" \
        "engine=${ENGINE}" \
        "engine_version=$("$ENGINE" version --format '{{.Server.Version}}')" \
        "image=${RUNTIME_IMAGE}" \
        "image_id=$(image_identity)" \
        "interrupt=${INTERRUPT_TARGET}" \
        "commit=$(git rev-parse HEAD 2> /dev/null || echo unknown)"
    exit 0
fi

_seed_fixture
_create_volume
_start_events
_submit_job

_wait_job_state "running" 180 \
    || die "Job ${JOB_ID} did not reach running"
RUNNING_AT_MS="$(_now_ms)"
_find_job_container
JS_BEFORE="$(_json_path "$HTTP_BODY" state)"
log "Job reached ${JS_BEFORE} with container ${CONTAINER_ID}"

_interrupt

_wait_job_state "succeeded failed cancelled timed_out expired" "$DRILL_TIMEOUT_SECONDS" \
    || die "Job ${JOB_ID} did not reach a terminal state after the interruption"
TERMINAL_AT_MS="$(_now_ms)"

_api GET "/api/jobs/${JOB_ID}" "$ADMIN_TOKEN"
_assert_eq "final job status" "$HTTP_STATUS" "200"
_assert_eq "final job state" "$(_json_path "$HTTP_BODY" state)" "succeeded"
_assert_eq "final job outcome" "$(_json_path "$HTTP_BODY" result.outcome_code)" "succeeded"
_assert_eq "final job exit code" "$(_json_path "$HTTP_BODY" result.exit_code)" "0"
_assert_eq "final job billing mode" "$(_json_path "$HTTP_BODY" billing.mode)" "zero_cost"
_assert_eq "final job charged credits" "$(_json_path "$HTTP_BODY" billing.charged)" "0"

_wait_cleanup || die "Job ${JOB_ID} cleanup did not complete"
CONTAINER_COUNT="$("$ENGINE" ps -a --filter "label=nukelab.job.id=${JOB_ID}" --format '{{.ID}}' | wc -l | tr -d ' ')"
_assert_eq "remaining workload containers" "$CONTAINER_COUNT" "0"

DB_ROW="$(
    _db_scalar "SELECT j.state || '|' || coalesce(j.outcome_code, '') || '|' || coalesce(j.exit_code::text, '') || '|' || coalesce(j.result_recorded_at::text, '') || '|' || j.reservation_active::text || '|' || j.billing_mode || '|' || j.charged_credits::text || '|' || coalesce(j.billing_transaction_id::text, '') || '|' || j.cleanup_state || '|' || coalesce(j.container_id, '') || '|' || (SELECT count(*) FROM volume_operations WHERE operation_id = j.id)::text || '|' || coalesce((SELECT state FROM volume_operations WHERE operation_id = j.id), '') || '|' || coalesce((SELECT completed_at::text FROM volume_operations WHERE operation_id = j.id), '') || '|' || (SELECT count(*) FROM credit_transactions WHERE user_id = j.user_id AND created_at >= j.created_at AND amount < 0)::text FROM batch_jobs j WHERE j.id = '${JOB_ID}'"
)"
_assert_nonempty "database job row" "$DB_ROW"
IFS='|' read -r DB_STATE DB_OUTCOME DB_EXIT DB_RESULT_AT DB_RESERVED DB_BILLING DB_CHARGED DB_TXN DB_CLEANUP DB_CONTAINER DB_GUARDS DB_GUARD_STATE DB_GUARD_COMPLETED DB_NEGATIVE_CREDITS <<< "$DB_ROW"

JOB_ROWS="$(_db_scalar "SELECT count(*) FROM batch_jobs WHERE id = '${JOB_ID}'")"
_assert_eq "job row count" "$JOB_ROWS" "1"
_assert_eq "database job state" "$DB_STATE" "succeeded"
_assert_eq "database outcome" "$DB_OUTCOME" "succeeded"
_assert_eq "database exit code" "$DB_EXIT" "0"
_assert_nonempty "database result timestamp" "$DB_RESULT_AT"
_assert_eq "reservation released" "$DB_RESERVED" "false"
_assert_eq "database billing mode" "$DB_BILLING" "zero_cost"
_assert_eq "database charged credits" "$DB_CHARGED" "0"
_assert_eq "database billing transaction" "$DB_TXN" ""
_assert_eq "database cleanup state" "$DB_CLEANUP" "complete"
_assert_nonempty "database container identity" "$DB_CONTAINER"
_assert_eq "volume guard rows" "$DB_GUARDS" "1"
_assert_eq "volume guard state" "$DB_GUARD_STATE" "succeeded"
_assert_nonempty "volume guard completion" "$DB_GUARD_COMPLETED"
_assert_eq "negative credit transactions" "$DB_NEGATIVE_CREDITS" "0"

if [ ! -s "$EVENTS_FILE" ]; then
    die "Container event capture produced no events"
fi
kill "$EVENTS_PID" 2> /dev/null || true
wait "$EVENTS_PID" 2> /dev/null || true
EVENTS_PID=""

EVENT_SUMMARY="$(_events_summary)"
EVENT_CREATES="$(_json_path "$EVENT_SUMMARY" create)"
EVENT_STARTS="$(_json_path "$EVENT_SUMMARY" start)"
_assert_eq "runtime create events" "$EVENT_CREATES" "1"
_assert_eq "runtime start events" "$EVENT_STARTS" "1"
EVENT_CONTAINER="$(
    python3 -c '
import json
import sys

print((json.loads(sys.argv[1]).get("create_ids") or [""])[0])
' "$EVENT_SUMMARY"
)"
EVENT_START_CONTAINER="$(
    python3 -c '
import json
import sys

print((json.loads(sys.argv[1]).get("start_ids") or [""])[0])
' "$EVENT_SUMMARY"
)"
_assert_eq "created runtime identity" "$EVENT_CONTAINER" "$DB_CONTAINER"
_assert_eq "started runtime identity" "$EVENT_START_CONTAINER" "$EVENT_CONTAINER"
_assert_eq "recorded and observed runtime" "$EVENT_CONTAINER" "$CONTAINER_ID"

TOTAL_MS=$((TERMINAL_AT_MS - SUBMIT_AT_MS))
RUNNING_MS=$((RUNNING_AT_MS - SUBMIT_AT_MS))
SETTLE_MS=$((TERMINAL_AT_MS - INTERRUPT_AT_MS))

step "Drill evidence"
_evidence \
    "scope=jobs-drill" \
    "commit=$(git rev-parse HEAD 2> /dev/null || echo unknown)" \
    "engine=${ENGINE}" \
    "engine_version=$("$ENGINE" version --format '{{.Server.Version}}')" \
    "image=${RUNTIME_IMAGE}" \
    "image_id=$(image_identity)" \
    "job=${JOB_ID}" \
    "interrupt=${INTERRUPT_TARGET}" \
    "submit_to_running_ms=${RUNNING_MS}" \
    "interrupt_to_terminal_ms=${SETTLE_MS}" \
    "submit_to_terminal_ms=${TOTAL_MS}" \
    "job_rows=${JOB_ROWS}" \
    "create_events=${EVENT_CREATES}" \
    "start_events=${EVENT_STARTS}" \
    "terminal_results=1" \
    "volume_guards=${DB_GUARDS}" \
    "guard_state=${DB_GUARD_STATE}" \
    "negative_credit_transactions=${DB_NEGATIVE_CREDITS}" \
    "cleanup_state=${DB_CLEANUP}"

ok "Interruption drill passed: one job, one runtime, one result, one released guard, zero billing"
