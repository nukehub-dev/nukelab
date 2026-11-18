#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Build, start, and wait on the disposable stack used by the browser e2e suite.
#
# Usage: scripts/ci/e2e-stack.sh <build [--workspace]|start|wait|stop|fixtures>
#
# Process environment values win over .env values, matching nukelabctl. Export
# CI overrides before invoking this script instead of appending duplicate keys
# to .env: load_env_file never overwrites an already-set variable, and the
# first occurrence inside a file wins.

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

FIXTURE_DIR="$REPO_ROOT/frontend/e2e/fixtures"
FIXTURE_DOCKERFILE="$FIXTURE_DIR/runtime.Dockerfile"
BASE_IMAGE="${E2E_BASE_IMAGE:-nukelab-environment-base:latest}"
RUNTIME_IMAGE="${E2E_RUNTIME_IMAGE:-nukelab-e2e-runtime:a}"
RUNTIME_IMAGE_B="${E2E_RUNTIME_IMAGE_B:-nukelab-e2e-runtime:b}"
HEALTH_URL="${E2E_HEALTH_URL:-http://127.0.0.1:8080/api/health}"
APP_READY_URL="${E2E_APP_READY_URL:-http://127.0.0.1:8080/}"
LOGIN_URL="${E2E_LOGIN_URL:-http://127.0.0.1:8080/api/auth/login}"
WAIT_TIMEOUT_SECONDS="${E2E_WAIT_TIMEOUT_SECONDS:-300}"
POLL_INTERVAL_SECONDS="${E2E_POLL_INTERVAL_SECONDS:-2}"
FIXTURE_CONTEXT_DIR=""

_cleanup_fixture_context() {
    if [ -n "$FIXTURE_CONTEXT_DIR" ] && [ -d "$FIXTURE_CONTEXT_DIR" ]; then
        rm -rf "$FIXTURE_CONTEXT_DIR" || true
    fi
}
trap '_cleanup_fixture_context' EXIT

usage() {
    cat <<- EOF
${BOLD}Usage:${RESET} scripts/ci/e2e-stack.sh <command> [options]

Manage the disposable NukeLab stack used by browser e2e runs.

${BOLD}Commands:${RESET}
  build [--workspace]  Build app, helper, base and fixture A/B images.
                       --workspace also builds conda-base and workspace.
  start                Start the production stack without rebuilding.
  wait                 Poll health, frontend and admin login readiness.
  stop                 Stop the stack, including spawned server containers.
  fixtures             Build only the A/B e2e runtime fixture images.

${BOLD}Environment:${RESET}
  CONTAINER_ENGINE             docker | podman (auto-detected when unset)
  E2E_BASE_IMAGE               Base image for fixtures (default: ${BASE_IMAGE})
  E2E_RUNTIME_IMAGE            Fixture A tag (default: ${RUNTIME_IMAGE})
  E2E_RUNTIME_IMAGE_B          Fixture B tag (default: ${RUNTIME_IMAGE_B})
  E2E_APP_READY_URL           Frontend readiness URL (default: ${APP_READY_URL})
  E2E_WAIT_TIMEOUT_SECONDS     Readiness deadline (default: ${WAIT_TIMEOUT_SECONDS})
  TEST_ADMIN_USERNAME          Login readiness user (default: admin)
  TEST_ADMIN_PASSWORD          Login readiness password (default: admin123)

${BOLD}Examples:${RESET}
  ./scripts/ci/e2e-stack.sh build
  ./scripts/ci/e2e-stack.sh build --workspace
  ./scripts/ci/e2e-stack.sh start
  ./scripts/ci/e2e-stack.sh wait
  ./scripts/ci/e2e-stack.sh stop
EOF
}

_require_engine() {
    if [ -n "${CONTAINER_ENGINE:-}" ] && command -v "$CONTAINER_ENGINE" > /dev/null 2>&1; then
        return 0
    fi
    detect_engine
}

_require_env_file() {
    if [ ! -f .env ] && [ ! -f .env.development ]; then
        die "No environment file found. Create one first:\n  cp .env.example .env"
    fi
}

_validate_positive_integer() {
    local name="$1"
    local value="$2"
    if ! [[ "$value" =~ ^[0-9]+$ ]] || [ "$value" -eq 0 ]; then
        die "${name} must be a positive integer, got: ${value}"
    fi
}

# Resolve the helper image tag from the process environment or the active env
# file without exporting unrelated values (notably NUKELAB_VERSION, which would
# switch nukelabctl into pull-deploy mode).
_helper_image() {
    local env_file=""
    if [ -f .env ]; then
        env_file=".env"
    elif [ -f .env.development ]; then
        env_file=".env.development"
    fi

    if [ -z "${VOLUME_BACKUP_HELPER_IMAGE:-}" ] && [ -n "$env_file" ]; then
        local -A env_values=()
        _read_env_into_assoc "$env_file" env_values
        if _assoc_has_key env_values VOLUME_BACKUP_HELPER_IMAGE; then
            VOLUME_BACKUP_HELPER_IMAGE="${env_values[VOLUME_BACKUP_HELPER_IMAGE]}"
        fi
    fi

    echo "${VOLUME_BACKUP_HELPER_IMAGE:-nukelab-volume-helper:latest}"
}

_build_helper() {
    _require_engine
    local image
    image="$(_helper_image)"

    # Build from the repository root because the helper copies the reviewed
    # backend archive module. Docker/BuildKit applies the per-Dockerfile
    # ignore file next to services/volume-helper/Dockerfile; pass it
    # explicitly when the engine exposes --ignorefile (for example Podman).
    local -a ignore_args=()
    local build_help=""
    build_help="$($CONTAINER_ENGINE build --help 2>&1 || true)"
    if [ "$CONTAINER_ENGINE" = "podman" ] && [[ "$build_help" == *--ignorefile* ]]; then
        ignore_args=(--ignorefile services/volume-helper/Dockerfile.dockerignore)
    fi

    log "Building volume helper image: ${image}"
    $CONTAINER_ENGINE build \
        "${ignore_args[@]}" \
        --tag "$image" \
        --file services/volume-helper/Dockerfile \
        .
}

_build_fixtures() {
    [ -f "$FIXTURE_DOCKERFILE" ] || die "Missing e2e fixture Dockerfile: ${FIXTURE_DOCKERFILE}"
    _require_engine

    # The fixture Dockerfile uses repo-root-relative COPY paths. Stage only the
    # fixture tree in a temporary repo-shaped context so the repository-root
    # .dockerignore cannot exclude those sources.
    FIXTURE_CONTEXT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/nukelab-e2e-fixtures.XXXXXX")"
    mkdir -p "$FIXTURE_CONTEXT_DIR/frontend/e2e"
    cp -R "$FIXTURE_DIR" "$FIXTURE_CONTEXT_DIR/frontend/e2e/fixtures"

    local variant image
    for variant in A B; do
        if [ "$variant" = "A" ]; then
            image="$RUNTIME_IMAGE"
        else
            image="$RUNTIME_IMAGE_B"
        fi
        log "Building e2e runtime fixture ${variant}: ${image}"
        $CONTAINER_ENGINE build \
            --file "$FIXTURE_CONTEXT_DIR/frontend/e2e/fixtures/runtime.Dockerfile" \
            --build-arg "BASE_IMAGE=${BASE_IMAGE}" \
            --build-arg "VARIANT=${variant}" \
            --tag "$image" \
            "$FIXTURE_CONTEXT_DIR"
    done

    rm -rf "$FIXTURE_CONTEXT_DIR"
    FIXTURE_CONTEXT_DIR=""
}

build_stack() {
    local with_workspace="$1"
    _require_env_file
    _require_engine

    log "Building backend and frontend images..."
    ./nukelabctl build backend
    ./nukelabctl build frontend

    _build_helper

    if [ "$with_workspace" = "true" ]; then
        log "Building base, conda-base and workspace environment images..."
        ./nukelabctl build env base conda-base workspace
    else
        log "Building base environment image..."
        ./nukelabctl build env base
    fi

    _build_fixtures
}

start_stack() {
    _require_env_file
    ./nukelabctl start all --no-build
}

_health_once() {
    curl -fsS --max-time 10 "$HEALTH_URL" > /dev/null
}

_frontend_once() {
    curl -fsS --max-time 10 "$APP_READY_URL" > /dev/null
}

_login_once() {
    curl -fsS --max-time 10 \
        --request POST \
        --header 'Content-Type: application/x-www-form-urlencoded' \
        --data-urlencode "username=${TEST_ADMIN_USERNAME:-admin}" \
        --data-urlencode "password=${TEST_ADMIN_PASSWORD:-admin123}" \
        --output /dev/null \
        "$LOGIN_URL"
}

_poll() {
    local description="$1"
    local timeout="$2"
    shift 2

    local deadline=$((SECONDS + timeout))
    log "Waiting for ${description} (timeout: ${timeout}s)..."
    while [ "$SECONDS" -lt "$deadline" ]; do
        if "$@" > /dev/null 2>&1; then
            ok "${description} is ready"
            return 0
        fi
        sleep "$POLL_INTERVAL_SECONDS"
    done
    return 1
}

wait_ready() {
    _validate_positive_integer "E2E_WAIT_TIMEOUT_SECONDS" "$WAIT_TIMEOUT_SECONDS"
    _validate_positive_integer "E2E_POLL_INTERVAL_SECONDS" "$POLL_INTERVAL_SECONDS"

    _poll "backend health" "$WAIT_TIMEOUT_SECONDS" _health_once \
        || die "Backend health did not become ready at ${HEALTH_URL} within ${WAIT_TIMEOUT_SECONDS}s"
    _poll "frontend" "$WAIT_TIMEOUT_SECONDS" _frontend_once \
        || die "Frontend did not become reachable at ${APP_READY_URL} within ${WAIT_TIMEOUT_SECONDS}s"
    _poll "admin login" "$WAIT_TIMEOUT_SECONDS" _login_once \
        || die "Admin login did not succeed at ${LOGIN_URL} within ${WAIT_TIMEOUT_SECONDS}s"
}

stop_stack() {
    _require_engine

    if [ -f .env ] || [ -f .env.development ]; then
        ./nukelabctl stop all --include-servers || warn "nukelabctl stop reported an error"
    fi

    # Stop spawned servers, recovery helpers, and toolchain helpers that may
    # outlive the compose stack. Only containers carrying the platform-managed
    # label are touched; unrelated host containers are left alone.
    local -a ids=()
    local id
    while IFS= read -r id; do
        [ -n "$id" ] && ids+=("$id")
    done < <(
        {
            $CONTAINER_ENGINE ps -q --filter "label=com.docker.compose.project=nukelab" || true
            $CONTAINER_ENGINE ps -q --filter "label=nukelab.managed=true" || true
        } 2> /dev/null | sort -u
    )

    if [ ${#ids[@]} -gt 0 ]; then
        log "Stopping remaining run-created containers..."
        $CONTAINER_ENGINE stop -t 10 "${ids[@]}" > /dev/null 2>&1 || true
    fi
}

command=""
case "${1:-}" in
    build | start | wait | stop | fixtures)
        command="$1"
        shift
        ;;
    -h | --help | help)
        usage
        exit 0
        ;;
    "")
        usage >&2
        exit 2
        ;;
    *)
        die "Unknown subcommand: $1\nRun '$0 --help' for usage."
        ;;
esac

case "$command" in
    build)
        with_workspace="false"
        while [ $# -gt 0 ]; do
            case "$1" in
                --workspace)
                    with_workspace="true"
                    shift
                    ;;
                *)
                    die "Unknown option for build: $1"
                    ;;
            esac
        done
        build_stack "$with_workspace"
        ;;
    start)
        [ $# -eq 0 ] || die "Unknown argument for start: $1"
        start_stack
        ;;
    wait)
        [ $# -eq 0 ] || die "Unknown argument for wait: $1"
        wait_ready
        ;;
    stop)
        [ $# -eq 0 ] || die "Unknown argument for stop: $1"
        stop_stack
        ;;
    fixtures)
        [ $# -eq 0 ] || die "Unknown argument for fixtures: $1"
        _build_fixtures
        ;;
esac
