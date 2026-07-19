#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# NukeLab shared helper library for management scripts.
# Source this from any script that needs environment loading or container-engine
# detection so the logic stays in one place.

# Provide plain fallbacks if the sourcing script does not define these helpers.
if ! type -t info | grep -q function 2> /dev/null; then
    info() { echo "ℹ  $*" >&2; }
fi
if ! type -t warn | grep -q function 2> /dev/null; then
    warn() { echo "⚠  $*" >&2; }
fi
if ! type -t die | grep -q function 2> /dev/null; then
    die() {
        echo "✗ $*" >&2
        exit 1
    }
fi

# ─── Colors ────────────────────────────────────────────────────────────────
# Emit ANSI escapes only when writing to a terminal and NO_COLOR is unset, so
# piped output (e.g. `./nukelabctl status | tee log`) stays clean.
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    RED=$'\033[0;31m'
    GREEN=$'\033[0;32m'
    YELLOW=$'\033[1;33m'
    BLUE=$'\033[0;34m'
    MAGENTA=$'\033[0;35m'
    CYAN=$'\033[0;36m'
    BOLD=$'\033[1m'
    DIM=$'\033[2m'
    RESET=$'\033[0m'
else
    RED='' GREEN='' YELLOW='' BLUE='' MAGENTA='' CYAN='' BOLD='' DIM='' RESET=''
fi

# ─── Logging ───────────────────────────────────────────────────────────────
# Levels: DEBUG < INFO < OK < WARN < ERROR. Default is INFO.
declare -A _LOG_LEVELS=([DEBUG]=0 [INFO]=1 [OK]=2 [WARN]=3 [ERROR]=4)
LOG_LEVEL="${LOG_LEVEL:-INFO}"
VERBOSE=false
QUIET=false

_log_level_value() {
    echo "${_LOG_LEVELS[$1]:-1}"
}

_log_should_print() {
    local requested="$1"
    local min
    min=$(_log_level_value "$LOG_LEVEL")
    local cur
    cur=$(_log_level_value "$requested")
    [[ $cur -ge $min ]]
}

log_debug() {
    _log_should_print DEBUG || return 0
    echo -e "${DIM}⛏ $*${RESET}" >&2
}
log_info() {
    _log_should_print INFO || return 0
    echo -e "${BLUE}▶${RESET} $*"
}
log_ok() {
    _log_should_print OK || return 0
    echo -e "${GREEN}✓${RESET}  $*"
}
log_warn() {
    _log_should_print WARN || return 0
    echo -e "${YELLOW}⚠${RESET}  $*" >&2
}
log_error() {
    _log_should_print ERROR || return 0
    echo -e "${RED}✗${RESET}  $*" >&2
}

# Backwards-compatible wrappers used by existing command modules.
log() { log_info "$@"; }
info() { log_info "$@"; }
ok() { log_ok "$@"; }
warn() { log_warn "$@"; }
err() { log_error "$@"; }
die() {
    log_error "$@"
    exit 1
}
step() {
    _log_should_print INFO || return 0
    echo -e "\n${BOLD}${MAGENTA}▸${RESET} ${BOLD}$*${RESET}"
}

# ─── Error Handling & Cleanup ──────────────────────────────────────────────
# These traps ensure the concurrency lock is always released and the user gets
# a clear message when something goes wrong.

_cleanup_trap() {
    _release_lock 2> /dev/null || true
}

_interrupt_trap() {
    log_warn "Interrupted by user"
    _release_lock 2> /dev/null || true
    exit 130
}

_error_trap() {
    local last_cmd="$BASH_COMMAND"
    local line_no="${BASH_LINENO[0]}"
    local src="${BASH_SOURCE[1]:-unknown}"
    log_error "Command failed in ${src}:${line_no}: ${last_cmd}"
    _release_lock 2> /dev/null || true
}

# ─── Environment Loading ───────────────────────────────────────────────────
# Usage: load_env_file <file>
# Exports KEY=VALUE lines from the file, skipping comments/blanks and stripping
# trailing inline comments. Variables already set (non-empty) in the environment
# are NOT overwritten, so shell exports take precedence.
load_env_file() {
    local env_file="$1"
    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ "$line" =~ ^[[:space:]]*#.*$ ]] && continue
        [[ -z "${line// /}" ]] && continue

        # Extract KEY=VALUE, then strip trailing inline comments
        # (only when # is preceded by whitespace, preserving # in passwords/URLs)
        local cleaned="$line"
        if [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)[[:space:]]+#.*$ ]]; then
            cleaned="${BASH_REMATCH[1]}=${BASH_REMATCH[2]}"
            while [[ "$cleaned" == *[[:space:]] ]]; do
                cleaned="${cleaned%[[:space:]]}"
            done
        fi

        # Only export if the variable is not already set in the environment
        local key="${cleaned%%=*}"
        if [ -z "${!key:-}" ]; then
            export "$cleaned" 2> /dev/null || true
        fi
    done < "$env_file"
}

# Usage: init_env [dev_mode]
# Loads .env as base defaults, then .env.development when dev_mode is true or
# when .env is missing and .env.development exists.
# Exports NUKELAB_ENV_FILE so compose services can reference the active env file.
init_env() {
    local dev_mode="${1:-false}"

    # Always load .env as base defaults
    if [ -f .env ]; then
        log "Loading ${BOLD}.env${RESET}"
        load_env_file .env
        export NUKELAB_ENV_FILE=".env"
    fi
    # In dev mode, overlay .env.development on top so dev values win
    if $dev_mode && [ -f .env.development ]; then
        log "Loading ${BOLD}.env.development${RESET} (dev overrides)"
        load_env_file .env.development
        export NUKELAB_ENV_FILE=".env.development"
    elif [ ! -f .env ] && [ -f .env.development ]; then
        log "Loading ${BOLD}.env.development${RESET}"
        load_env_file .env.development
        export NUKELAB_ENV_FILE=".env.development"
    elif [ ! -f .env ] && [ ! -f .env.development ]; then
        die "No environment file found.\n\n  cp .env.example .env.development"
    fi
}

# ─── Container Engine ─────────────────────────────────────────────────────-
# Usage: detect_engine
# Sets CONTAINER_ENGINE (podman|docker) and COMPOSE (podman-compose,
# docker-compose, or "<engine> compose").
detect_engine() {
    # A pre-set CONTAINER_ENGINE (docker|podman) wins over auto-detection so
    # users with both runtimes installed are not forced into podman.
    if [ "${CONTAINER_ENGINE:-}" = "docker" ] && command -v docker > /dev/null 2>&1; then
        info "Docker detected (via CONTAINER_ENGINE)"
    elif [ "${CONTAINER_ENGINE:-}" = "podman" ] && command -v podman > /dev/null 2>&1; then
        info "Podman detected (via CONTAINER_ENGINE)"
    elif command -v podman > /dev/null 2>&1; then
        CONTAINER_ENGINE=podman
        info "Podman detected"
    elif command -v docker > /dev/null 2>&1; then
        CONTAINER_ENGINE=docker
        info "Docker detected"
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
}

# Usage: build_environment_image <caller_script_dir> <name> <env_dir> <tag> [extra_args...]
# Builds an environment image using the detected container engine.
# <caller_script_dir> is the directory containing the invoking build-*.sh script.
# Optional extra_args are forwarded to the container engine build command.
build_environment_image() {
    local caller_dir="$1"
    local name="$2"
    local env_dir="$3"
    local tag="$4"
    shift 4
    local extra_args=("$@")
    local root
    root="$(cd "$caller_dir/../.." > /dev/null 2>&1 && pwd)"

    if [ -z "${CONTAINER_ENGINE:-}" ]; then
        detect_engine
    fi

    log "Building NukeLab $name..."
    cd "$root/environments/$env_dir"
    $CONTAINER_ENGINE build -t "$tag" "${extra_args[@]}" .

    log_ok "$name built successfully!"
}

# Usage: setup_podman_socket
# When running under Podman, ensure DOCKER_SOCKET points to the active API socket.
setup_podman_socket() {
    [ "$CONTAINER_ENGINE" != "podman" ] && return

    # Env files do not perform shell expansion, so a value like
    # ${XDG_RUNTIME_DIR}/podman/podman.sock is taken literally. Replace any
    # literal reference with the actual variable value, and collapse the
    # common copy-paste mistake /run/user/1000${XDG_RUNTIME_DIR}/... so the
    # path becomes valid.
    if [ -n "${DOCKER_SOCKET:-}" ] && [ -n "${XDG_RUNTIME_DIR:-}" ]; then
        DOCKER_SOCKET="${DOCKER_SOCKET//\$\{XDG_RUNTIME_DIR\}/$XDG_RUNTIME_DIR}"
        DOCKER_SOCKET="${DOCKER_SOCKET//\$XDG_RUNTIME_DIR/$XDG_RUNTIME_DIR}"
        while [[ "$DOCKER_SOCKET" == *"$XDG_RUNTIME_DIR$XDG_RUNTIME_DIR"* ]]; do
            DOCKER_SOCKET="${DOCKER_SOCKET/$XDG_RUNTIME_DIR$XDG_RUNTIME_DIR/$XDG_RUNTIME_DIR}"
        done
    fi

    # If DOCKER_SOCKET is set but doesn't exist, override it
    if [ -n "${DOCKER_SOCKET:-}" ] && [ ! -S "$DOCKER_SOCKET" ]; then
        warn "DOCKER_SOCKET=$DOCKER_SOCKET not found, auto-detecting..."
        unset DOCKER_SOCKET
    fi

    # Auto-detect if not set
    if [ -z "${DOCKER_SOCKET:-}" ]; then
        SOCK=$(podman info --format '{{.Host.RemoteSocket.Path}}' 2> /dev/null || true)
        if [ -n "$SOCK" ]; then
            export DOCKER_SOCKET="$SOCK"
        elif [ -n "${XDG_RUNTIME_DIR:-}" ] && [ -S "$XDG_RUNTIME_DIR/podman/podman.sock" ]; then
            export DOCKER_SOCKET="$XDG_RUNTIME_DIR/podman/podman.sock"
        else
            export DOCKER_SOCKET="/run/podman/podman.sock"
        fi
        info "Using Podman socket: $DOCKER_SOCKET"
    fi

    export DOCKER_NUKELAB_HOST="$DOCKER_SOCKET"
}

# ─── State Persistence ─────────────────────────────────────────────────────
# Remember the compose configuration used at start so stop/status/logs/etc.
# operate on the actual stack even when env vars are no longer exported.

persist_state() {
    local tmp_state="${STATE_FILE}.tmp.$$"
    {
        echo "# NukeLab runtime state — auto-generated by nukelabctl"
        echo "# Do not edit by hand; delete this file to force env-based fallback."
        echo "NUKELAB_USE_DEV_MODE=$USE_DEV_MODE"
        echo "NUKELAB_TARGET=$TARGET"
        echo "NUKELAB_PGBOUNCER_ENABLED=${PGBOUNCER_ENABLED:-false}"
        echo "NUKELAB_PROMETHEUS_ENABLED=${PROMETHEUS_ENABLED:-false}"
        echo "NUKELAB_GRAFANA_ENABLED=${GRAFANA_ENABLED:-false}"
        echo "NUKELAB_ALERTMANAGER_ENABLED=${ALERTMANAGER_ENABLED:-false}"
        echo "NUKELAB_TRACING_ENABLED=${TRACING_ENABLED:-false}"
        printf 'NUKELAB_COMPOSE_ARGS=('
        local first=true
        for arg in "${COMPOSE_ARGS[@]}"; do
            if $first; then
                first=false
            else
                printf ' '
            fi
            printf '%q' "$arg"
        done
        printf ')\n'
    } > "$tmp_state"
    mv "$tmp_state" "$STATE_FILE"
}

restore_state() {
    if [ ! -f "$STATE_FILE" ]; then
        return 1
    fi

    # Capture env values and the command-line target before the state file
    # overwrites them. The user-specified target always wins over saved state.
    local _orig_target="$TARGET"
    local _orig_pgbouncer="${PGBOUNCER_ENABLED:-}"
    local _orig_prometheus="${PROMETHEUS_ENABLED:-}"
    local _orig_grafana="${GRAFANA_ENABLED:-}"
    local _orig_alertmanager="${ALERTMANAGER_ENABLED:-}"
    local _orig_tracing="${TRACING_ENABLED:-}"

    # shellcheck source=/dev/null
    source "$STATE_FILE"

    TARGET="$_orig_target"

    # The state file is already mode-specific (prod vs dev), so the saved mode
    # should match the current command. If it doesn't, trust the current mode
    # and let setup_compose_args rebuild the correct project args.
    if [ "${NUKELAB_USE_DEV_MODE:-false}" != "$USE_DEV_MODE" ]; then
        warn "State file mode (${NUKELAB_USE_DEV_MODE:-false}) does not match current command (dev=$USE_DEV_MODE); using current mode"
        return 1
    fi

    PGBOUNCER_ENABLED="${NUKELAB_PGBOUNCER_ENABLED:-false}"
    PROMETHEUS_ENABLED="${NUKELAB_PROMETHEUS_ENABLED:-false}"
    GRAFANA_ENABLED="${NUKELAB_GRAFANA_ENABLED:-false}"
    ALERTMANAGER_ENABLED="${NUKELAB_ALERTMANAGER_ENABLED:-false}"
    TRACING_ENABLED="${NUKELAB_TRACING_ENABLED:-false}"

    if [ ${#NUKELAB_COMPOSE_ARGS[@]} -gt 0 ]; then
        COMPOSE_ARGS=("${NUKELAB_COMPOSE_ARGS[@]}")
    fi

    # Dev compose file is generated by setup_compose_args; recreate it if missing
    # so restored COMPOSE_ARGS remain valid.
    if $USE_DEV_MODE && [ ! -f "$DEV_COMPOSE_FILE" ]; then
        cat > "$DEV_COMPOSE_FILE" << 'EOF'
services:
  backend:
    command:
      - uvicorn
      - app.main:app
      - --host
      - 0.0.0.0
      - --port
      - "8000"
      - --reload
      - --reload-dir
      - /app/app
      - --reload-exclude
      - "*__pycache__*"
      - --reload-exclude
      - "*.pyc"
      - --timeout-keep-alive
      - "30"
    volumes:
      - ./backend:/app:Z
      - ./resources:/app/resources:ro
  celery-worker:
    volumes:
      - ./backend:/app:Z
      - ./resources:/app/resources:ro
  celery-beat:
    volumes:
      - ./backend:/app:Z
      - ./resources:/app/resources:ro
EOF
    fi

    info "Restoring compose configuration from previous start"

    # Warn when the current environment contradicts the persisted state.
    if [ -n "$_orig_pgbouncer" ] && [ "$_orig_pgbouncer" != "$PGBOUNCER_ENABLED" ]; then
        warn "PGBOUNCER_ENABLED=$PGBOUNCER_ENABLED (from state) overrides current env value $_orig_pgbouncer"
    fi
    if [ -n "$_orig_prometheus" ] && [ "$_orig_prometheus" != "$PROMETHEUS_ENABLED" ]; then
        warn "PROMETHEUS_ENABLED=$PROMETHEUS_ENABLED (from state) overrides current env value $_orig_prometheus"
    fi
    if [ -n "$_orig_grafana" ] && [ "$_orig_grafana" != "$GRAFANA_ENABLED" ]; then
        warn "GRAFANA_ENABLED=$GRAFANA_ENABLED (from state) overrides current env value $_orig_grafana"
    fi
    if [ -n "$_orig_alertmanager" ] && [ "$_orig_alertmanager" != "$ALERTMANAGER_ENABLED" ]; then
        warn "ALERTMANAGER_ENABLED=$ALERTMANAGER_ENABLED (from state) overrides current env value $_orig_alertmanager"
    fi
    if [ -n "$_orig_tracing" ] && [ "$_orig_tracing" != "$TRACING_ENABLED" ]; then
        warn "TRACING_ENABLED=$TRACING_ENABLED (from state) overrides current env value $_orig_tracing"
    fi

    return 0
}

clear_state() {
    rm -f "$STATE_FILE"
    rm -f "$DEV_COMPOSE_FILE"
    rm -f "$FRONTEND_PID_FILE"
}

# ─── Mutual Exclusion ──────────────────────────────────────────────────────
# Dev and prod share container names, so only one may run at a time.
# These helpers detect whether a stack is running and refuse to start a new
# one when the opposite stack is active.

# Return 0 if any container matching the project prefix is running.
_project_containers_running() {
    local _cmd="podman"
    [ "$CONTAINER_ENGINE" = "docker" ] && _cmd="docker"
    $_cmd ps --format '{{.Names}}' 2> /dev/null | grep -qE '^nukelab-'
}

# Warn when NukeLab containers are running but we have no state file. This
# usually means a previous run left orphans behind.
_warn_stale_containers() {
    if [ ! -f "$STATE_FILE" ] && _project_containers_running; then
        warn "NukeLab containers are already running but no state file was found ($STATE_FILE)."
        info "This can happen if a previous run crashed or the state file was deleted."
        info "Stop them first to avoid conflicts:"
        echo "  ./nukelabctl stop"
        echo "  # or, if the state file is missing:"
        echo "  $CONTAINER_ENGINE stop \$($CONTAINER_ENGINE ps -q --filter name=^nukelab-)"
        echo "  $CONTAINER_ENGINE rm -f \$($CONTAINER_ENGINE ps -aq --filter name=^nukelab-)"
    fi
}

# Return 0 if any service managed by the current COMPOSE_ARGS is running.
_is_stack_running() {
    $COMPOSE "${COMPOSE_ARGS[@]}" ps --format json 2> /dev/null | grep -q '"State": "running"' \
        || $COMPOSE "${COMPOSE_ARGS[@]}" ps 2> /dev/null | grep -qE 'Up[[:space:]]+[a-z0-9-]+$'
}

# Return 0 if the opposite-mode stack is currently running.
_other_stack_running() {
    local other_state_file
    if $USE_DEV_MODE; then
        other_state_file="$PROD_STATE_FILE"
    else
        other_state_file="$DEV_STATE_FILE"
    fi

    [ -f "$other_state_file" ] || return 1

    # Temporarily source the other state file and ask compose whether any of
    # its services are up. We restore COMPOSE_ARGS afterwards.
    local _saved_args=("${COMPOSE_ARGS[@]}")
    # shellcheck source=/dev/null
    source "$other_state_file"
    if [ ${#NUKELAB_COMPOSE_ARGS[@]} -gt 0 ]; then
        COMPOSE_ARGS=("${NUKELAB_COMPOSE_ARGS[@]}")
    else
        COMPOSE_ARGS=(-f "$COMPOSE_FILE")
    fi

    local _running=false
    if _is_stack_running; then
        _running=true
    fi

    COMPOSE_ARGS=("${_saved_args[@]}")
    $_running
}

# Block start when the opposite stack is running.
_require_other_stack_stopped() {
    if _other_stack_running; then
        if $USE_DEV_MODE; then
            die "Production stack is already running.\n\nStop it first:\n  ./nukelabctl stop\n\nThen run:\n  ./nukelabctl dev start"
        else
            die "Development stack is already running.\n\nStop it first:\n  ./nukelabctl dev stop\n\nThen run:\n  ./nukelabctl start"
        fi
    fi
}

# ─── Compose Args ──────────────────────────────────────────────────────────
setup_compose_args() {
    # Option B: dev and prod are mutually exclusive stacks using the same
    # Compose project and container names. Only one may be running at a time.
    COMPOSE_ARGS=(-f "$COMPOSE_FILE")

    if $USE_DEV_MODE; then
        cat > "$DEV_COMPOSE_FILE" << 'EOF'
services:
  backend:
    command:
      - uvicorn
      - app.main:app
      - --host
      - 0.0.0.0
      - --port
      - "8000"
      - --reload
      - --reload-dir
      - /app/app
      - --reload-exclude
      - "*__pycache__*"
      - --reload-exclude
      - "*.pyc"
      - --timeout-keep-alive
      - "30"
    volumes:
      - ./backend:/app:Z
      - ./resources:/app/resources:ro
  celery-worker:
    volumes:
      - ./backend:/app:Z
      - ./resources:/app/resources:ro
  celery-beat:
    volumes:
      - ./backend:/app:Z
      - ./resources:/app/resources:ro
EOF
        COMPOSE_ARGS+=(-f "$DEV_COMPOSE_FILE")
    else
        rm -f "$DEV_COMPOSE_FILE"
    fi

    # Include overlays from env var (space-separated) and CLI flags
    if [ -n "${COMPOSE_OVERLAYS:-}" ]; then
        read -ra _env_overlays <<< "$COMPOSE_OVERLAYS"
        COMPOSE_OVERLAY_FILES+=("${_env_overlays[@]}")
    fi

    # Auto-inject PgBouncer overlay when explicitly enabled
    if [ "${PGBOUNCER_ENABLED:-false}" = "true" ]; then
        local _pgbouncer_overlay="compose.pgbouncer.yml"
        local _pgbouncer_found=false
        for _o in "${COMPOSE_OVERLAY_FILES[@]}"; do
            if [ "$_o" = "$_pgbouncer_overlay" ]; then
                _pgbouncer_found=true
                break
            fi
        done
        if ! $_pgbouncer_found; then
            COMPOSE_OVERLAY_FILES+=("$_pgbouncer_overlay")
            info "Adding overlay $_pgbouncer_overlay"
        fi

        # Warn if the database host/port point to PgBouncer (migrations should use direct Postgres)
        if [[ "${DATABASE_HOST:-postgres}" == "pgbouncer" ]] || [[ "${DATABASE_PORT:-5432}" == "6432" ]]; then
            warn "Database host/port point to PgBouncer. Migrations should use direct Postgres."
            info "Hint: Keep DATABASE_HOST=postgres and DATABASE_PORT=5432 for DDL/migrations"
        fi
    fi

    # Auto-inject monitoring overlay when Prometheus or Grafana is enabled.
    # Skip it during backend tests to avoid postgres-exporter consuming
    # connections and competing with the test database.
    if [ "${CMD:-}" != "test" ] && ([[ "${PROMETHEUS_ENABLED:-false}" == "true" ]] || [[ "${GRAFANA_ENABLED:-false}" == "true" ]]); then
        local _monitoring_overlays=("compose.monitoring.yml")
        if [ "${PGBOUNCER_ENABLED:-false}" = "true" ]; then
            _monitoring_overlays+=("compose.monitoring-pgbouncer.yml")
        fi
        for _monitoring_overlay in "${_monitoring_overlays[@]}"; do
            local _monitoring_found=false
            for _o in "${COMPOSE_OVERLAY_FILES[@]}"; do
                if [ "$_o" = "$_monitoring_overlay" ]; then
                    _monitoring_found=true
                    break
                fi
            done
            if ! $_monitoring_found; then
                COMPOSE_OVERLAY_FILES+=("$_monitoring_overlay")
                info "Adding overlay $_monitoring_overlay"
            fi
        done
    fi

    # Auto-inject Alertmanager overlay when enabled
    if [ "${NO_ALERTMANAGER:-false}" = "true" ]; then
        log_debug "Skipping Alertmanager overlay (--no-alertmanager / test mode)"
    elif [[ "${ALERTMANAGER_ENABLED:-false}" == "true" ]]; then
        local _alertmanager_overlay="compose.alertmanager.yml"
        local _alertmanager_found=false
        for _o in "${COMPOSE_OVERLAY_FILES[@]}"; do
            if [ "$_o" = "$_alertmanager_overlay" ]; then
                _alertmanager_found=true
                break
            fi
        done
        if ! $_alertmanager_found; then
            COMPOSE_OVERLAY_FILES+=("$_alertmanager_overlay")
            info "Adding overlay $_alertmanager_overlay"
        fi
    fi

    # Auto-inject tracing overlay when enabled
    if [[ "${TRACING_ENABLED:-false}" == "true" ]]; then
        local _tracing_overlay="compose.tracing.yml"
        local _tracing_found=false
        for _o in "${COMPOSE_OVERLAY_FILES[@]}"; do
            if [ "$_o" = "$_tracing_overlay" ]; then
                _tracing_found=true
                break
            fi
        done
        if ! $_tracing_found; then
            COMPOSE_OVERLAY_FILES+=("$_tracing_overlay")
            info "Adding overlay $_tracing_overlay"
        fi
    fi

    # Deduplicate
    declare -A _seen_overlays
    for overlay in "${COMPOSE_OVERLAY_FILES[@]}"; do
        if [ -z "${_seen_overlays[$overlay]:-}" ]; then
            _seen_overlays[$overlay]=1
            if [ -f "$overlay" ]; then
                COMPOSE_ARGS+=(-f "$overlay")
            else
                warn "Compose overlay not found: $overlay"
            fi
        fi
    done
}

# ─── Pre-flight Validation ─────────────────────────────────────────────────
# Usage: preflight_checks
# Performs a set of cheap, host-side sanity checks before mutating commands
# such as start/build/update/test. Prints actionable errors and exits on
# failure. Set SKIP_PORT_CHECK=true to bypass the port checks.

_preflight_port_in_use() {
    local port="$1"
    if command -v ss > /dev/null 2>&1; then
        ss -tln 2> /dev/null | grep -Eq ":${port}[[:space:]]" && return 0
    elif command -v netstat > /dev/null 2>&1; then
        netstat -tln 2> /dev/null | grep -Eq ":${port}[[:space:]]" && return 0
    else
        # No tool available — warn once but do not block.
        return 1
    fi
    return 1
}

_preflight_check_ports() {
    local ports=(8080 8443)
    if $USE_DEV_MODE; then
        ports+=(5173)
    fi
    if [ "${PGBOUNCER_ENABLED:-false}" = "true" ]; then
        ports+=(6432)
    fi
    if [ "${TRACING_ENABLED:-false}" = "true" ]; then
        ports+=(4317 4318)
    fi

    local busy=()
    for port in "${ports[@]}"; do
        if _preflight_port_in_use "$port"; then
            busy+=("$port")
        fi
    done

    if [ ${#busy[@]} -gt 0 ]; then
        die "Port(s) already in use: ${busy[*]}\n\nFree them or choose different ports.\nUse --skip-port-check to bypass this check."
    fi
}

preflight_checks() {
    log_debug "Running pre-flight checks"

    # 1. Environment files
    if $USE_DEV_MODE; then
        if [ ! -f .env ] && [ ! -f .env.development ]; then
            die "No environment file found.\n\n  cp .env.example .env.development"
        fi
    else
        if [ ! -f .env ] && [ ! -f .env.development ]; then
            die "No environment file found.\n\n  cp .env.example .env"
        fi
    fi

    # 2. Container engine and daemon/socket reachability
    if ! command -v "$CONTAINER_ENGINE" > /dev/null 2>&1; then
        die "Container engine '$CONTAINER_ENGINE' not found"
    fi
    if ! "$CONTAINER_ENGINE" info > /dev/null 2>&1; then
        die "Container engine '$CONTAINER_ENGINE' is not running or not reachable\n\nPodman: podman machine start\nDocker: sudo systemctl start docker"
    fi

    # 3. Production secrets sanity check
    if [ "${APP_ENV:-development}" = "production" ]; then
        local jwt="${JWT_SECRET:-}"
        if [ -z "$jwt" ] || [[ "$jwt" == dev-jwt-secret-change-in-production* ]] || [ "${#jwt}" -lt 32 ]; then
            die "JWT_SECRET is unset or still using the development default.\nSet a strong, unique secret before running in production."
        fi

        local session="${SESSION_SECRET:-}"
        if [ -z "$session" ] || [[ "$session" == dev-session-secret-change-in-production* ]]; then
            die "SESSION_SECRET is unset or still using the development default.\nSet a strong, unique secret before running in production."
        fi
    fi

    # 4. Volume storage path
    # Required in both dev and prod because compose.yml mounts it into backend
    # and backend-test services.
    if [ -z "${VOLUME_STORAGE_PATH:-}" ]; then
        die "VOLUME_STORAGE_PATH is required but not set.\n\nSet it in .env or .env.development, for example:\n  VOLUME_STORAGE_PATH=/var/lib/nukelab/volumes\n\nFor local development you can use:\n  VOLUME_STORAGE_PATH=/tmp/nukelab-volumes"
    fi
    if [ ! -d "$VOLUME_STORAGE_PATH" ]; then
        if [ "${APP_ENV:-development}" = "production" ]; then
            die "VOLUME_STORAGE_PATH does not exist: $VOLUME_STORAGE_PATH"
        else
            warn "Creating VOLUME_STORAGE_PATH directory: $VOLUME_STORAGE_PATH"
            mkdir -p "$VOLUME_STORAGE_PATH" || die "Failed to create $VOLUME_STORAGE_PATH"
        fi
    fi

    # 5. Ports
    if [ "${SKIP_PORT_CHECK:-false}" != "true" ]; then
        _preflight_check_ports
    else
        log_debug "Skipping port checks (--skip-port-check)"
    fi

    log_debug "Pre-flight checks passed"
}

# ─── Concurrency Lock ──────────────────────────────────────────────────────
# Prevents two nukelabctl invocations from running conflicting operations at the
# same time. The lock file stores the PID and command of the holding process.

LOCK_DIR="${XDG_RUNTIME_DIR:-$HOME/.local/share}/nukelab"
LOCK_FILE="$LOCK_DIR/manage.lock"

_acquire_lock() {
    mkdir -p "$LOCK_DIR"
    if [ -f "$LOCK_FILE" ]; then
        local other_pid
        other_pid=$(awk 'NR==1' "$LOCK_FILE" 2> /dev/null || true)
        if [ -n "$other_pid" ] && kill -0 "$other_pid" 2> /dev/null; then
            local other_cmd
            other_cmd=$(sed -n '2p' "$LOCK_FILE" 2> /dev/null || true)
            die "Another nukelabctl process is already running (PID $other_pid, command: ${other_cmd:-unknown}).\nWait for it to finish or remove $LOCK_FILE if it crashed."
        fi
        warn "Stale lock found (PID ${other_pid:-unknown}). Removing..."
        rm -f "$LOCK_FILE"
    fi
    echo "$$" > "$LOCK_FILE"
    echo "$CMD ${TARGET:-}" >> "$LOCK_FILE"
    trap '_release_lock' EXIT INT TERM
}

_release_lock() {
    if [ -f "$LOCK_FILE" ] && [ "$(awk 'NR==1' "$LOCK_FILE" 2> /dev/null || true)" = "$$" ]; then
        rm -f "$LOCK_FILE"
    fi
}

# ─── Output Helpers ────────────────────────────────────────────────────────
# Run a command, hiding stdout unless --verbose is set. stderr is always shown
# so failures are visible.
_run_quiet_unless_verbose() {
    if $VERBOSE; then
        "$@"
    else
        "$@" > /dev/null
    fi
}

# Bring up services, suppressing the noisy "no container with name ..." warnings
# compose prints on a fresh start/restart unless --verbose is requested. The
# companion --build/--no-build flag is selected by START_BUILD which is set by
# parse_start_args / parse_restart_args before this is called.
_start_compose_up() {
    local _up_args=(-d)
    if ${START_BUILD:-true}; then
        _up_args+=(--build)
    else
        _up_args+=(--no-build)
    fi

    if $VERBOSE; then
        _run_quiet_unless_verbose $COMPOSE "${COMPOSE_ARGS[@]}" up "${_up_args[@]}" "$@"
    else
        local _up_out
        _up_out=$(mktemp)
        if ! $COMPOSE "${COMPOSE_ARGS[@]}" up "${_up_args[@]}" "$@" > "$_up_out" 2>&1; then
            cat "$_up_out" >&2
            rm -f "$_up_out"
            return 1
        fi
        rm -f "$_up_out"
    fi
}

# ─── Service / Container Helpers ───────────────────────────────────────────
is_frontend_running() {
    [ -f "$FRONTEND_PID_FILE" ] && kill -0 "$(cat "$FRONTEND_PID_FILE")" 2> /dev/null
}

kill_frontend() {
    if is_frontend_running; then
        local pid=$(cat "$FRONTEND_PID_FILE")
        log "Stopping frontend (PID: $pid)..."
        # Vite is spawned by npm/node; kill child processes first so the
        # dev server does not outlive the PID file.
        local children
        children=$(pgrep -P "$pid" 2> /dev/null || true)
        if [ -n "$children" ]; then
            kill $children 2> /dev/null || true
            sleep 0.2
        fi
        kill "$pid" 2> /dev/null || true
        rm -f "$FRONTEND_PID_FILE"
        ok "Frontend stopped"
    fi
}

_container_exists() {
    local name="$1"
    local _cmd="podman"
    [ "$CONTAINER_ENGINE" = "docker" ] && _cmd="docker"
    $_cmd ps -a --filter "name=^${name}$" --format "{{.Names}}" 2> /dev/null | grep -qx "$name"
}

_container_running() {
    local name="$1"
    local _cmd="podman"
    [ "$CONTAINER_ENGINE" = "docker" ] && _cmd="docker"
    $_cmd ps --filter "name=^${name}$" --filter "status=running" --format "{{.Names}}" 2> /dev/null | grep -qx "$name"
}

_stop_orphan_container() {
    local name="$1"
    local _cmd="podman"
    [ "$CONTAINER_ENGINE" = "docker" ] && _cmd="docker"
    if $_cmd ps --filter "name=^${name}$" --filter "status=running" --format "{{.Names}}" 2> /dev/null | grep -qx "$name"; then
        log "Stopping orphan container ${BOLD}$name${RESET}..."
        $_cmd stop -t 10 "$name" > /dev/null 2>&1 || true
    fi
}

# Stop a container only when it is not already managed through compose.
_stop_orphan_if_unmanaged() {
    local overlay="$1"
    local name="$2"
    # If the current compose configuration already includes the overlay,
    # the regular compose stop/rm will handle it; no orphan cleanup needed.
    if _has_overlay "$overlay"; then
        return
    fi
    _stop_orphan_container "$name"
}

is_backend_container_running() {
    # Check via compose first (respects selected overlays), but fall back to
    # checking the container engine directly. This lets `nukelabctl test backend`
    # work even when the stack was started with a slightly different set of
    # overlays (e.g. dev mode) because the container name stays the same.
    if $COMPOSE "${COMPOSE_ARGS[@]}" ps 2> /dev/null | grep -q 'Up .*nukelab-backend'; then
        return 0
    fi

    local _container_cmd="podman"
    if [ "$CONTAINER_ENGINE" = "docker" ]; then
        _container_cmd="docker"
    fi
    $_container_cmd ps --filter "name=^nukelab-backend$" --filter "status=running" --format "{{.Names}}" 2> /dev/null | grep -qx "nukelab-backend"
}

_has_overlay() {
    # Return 0 if the given compose overlay file is in COMPOSE_ARGS.
    local file="$1"
    for arg in "${COMPOSE_ARGS[@]}"; do
        if [[ "$arg" == "$file" ]]; then
            return 0
        fi
    done
    return 1
}

_backend_services() {
    # Print the list of backend services, including PgBouncer, monitoring, and
    # tracing overlays when enabled.
    local services="traefik postgres redis backend celery-worker celery-beat"
    if _has_overlay "compose.pgbouncer.yml"; then
        services="$services pgbouncer"
    fi
    if _has_overlay "compose.monitoring.yml"; then
        services="$services prometheus grafana postgres-exporter redis-exporter node-exporter celery-exporter"
    fi
    if _has_overlay "compose.alertmanager.yml"; then
        services="$services alertmanager"
    fi
    if _has_overlay "compose.tracing.yml"; then
        services="$services otel-collector jaeger"
    fi
    echo "$services"
}

_stop_dev_stack() {
    # Dev-mode Ctrl+C handler: stop Vite and all backend/monitoring/tracing containers.
    echo ""
    step "Shutting down..."
    kill_frontend
    $COMPOSE "${COMPOSE_ARGS[@]}" stop $(_backend_services) > /dev/null 2>&1 || true
    _stop_orphan_if_unmanaged "compose.pgbouncer.yml" nukelab-pgbouncer
    _stop_orphan_if_unmanaged "compose.tracing.yml" nukelab-otel-collector
    _stop_orphan_if_unmanaged "compose.tracing.yml" nukelab-jaeger
    _release_lock 2> /dev/null || true
    ok "Goodbye!"
    exit 0
}

setup_cpu_lib_volume() {
    local vol_name="nukelab-cpu-lib"
    local c_file="$DIR/resources/lib/nukelab/libnukelab_cpu.c"

    if [ ! -f "$c_file" ]; then
        warn "CPU mask source not found: $c_file"
        return
    fi

    # Skip if volume already exists
    if $CONTAINER_ENGINE volume inspect "$vol_name" > /dev/null 2>&1; then
        return
    fi

    step "Setting up CPU mask library..."

    # Create volume
    $CONTAINER_ENGINE volume create "$vol_name" > /dev/null
    ok "Created volume: $vol_name"

    # Build .so inside a temporary gcc container
    log "Building libnukelab_cpu.so (one-time)..."
    local tmp_name="nukelab-tmp-build-cpu-lib"
    local build_image="docker.io/library/gcc:latest"

    # Pull gcc image if not present
    if ! $CONTAINER_ENGINE image exists "$build_image" 2> /dev/null; then
        log "Pulling $build_image..."
        $CONTAINER_ENGINE pull "$build_image" > /dev/null 2>&1 || {
            warn "Failed to pull $build_image"
            warn "Check your internet connection or container registry access"
            return
        }
    fi

    # Create temp container with volume mounted
    $CONTAINER_ENGINE run --rm -d \
        --name "$tmp_name" \
        -v "$vol_name:/dst" \
        -v "$c_file:/src/libnukelab_cpu.c:ro" \
        "$build_image" \
        sleep 3600 > /dev/null 2>&1 || {
        warn "Failed to start build container"
        return
    }

    # Compile
    $CONTAINER_ENGINE exec "$tmp_name" \
        gcc -shared -fPIC -o /dst/libnukelab_cpu.so /src/libnukelab_cpu.c -ldl

    local exit_code=$?
    $CONTAINER_ENGINE rm -f "$tmp_name" > /dev/null 2>&1

    if [ $exit_code -ne 0 ]; then
        err "Failed to build libnukelab_cpu.so"
        $CONTAINER_ENGINE volume rm "$vol_name" > /dev/null 2>&1 || true
        return
    fi

    ok "Built and stored libnukelab_cpu.so in volume"
}

# Returns a direct Postgres URL built from the database component env vars.
# This is useful for migrations and other DDL operations that must not go
# through PgBouncer.
_direct_database_url() {
    echo "postgresql+asyncpg://${DATABASE_USER:-nukelab}:${DATABASE_PASSWORD:-nukelab123}@${DATABASE_HOST:-postgres}:${DATABASE_PORT:-5432}/${DATABASE_NAME:-nukelab}"
}

wait_for_backend() {
    # Always check the local Traefik-exposed backend, not APP_URL. APP_URL may
    # point to an external hostname (e.g., https://lab.nukehub.org) that isn't
    # reachable from the host running nukelabctl during initial startup.
    local url="http://localhost:8080/api/health"
    local waited=0
    step "Waiting for backend..."
    while ! curl -sf "$url" > /dev/null 2>&1; do
        sleep 2
        waited=$((waited + 2))
        [ "$waited" -ge 60 ] && {
            warn "Timeout, continuing..."
            return 1
        }
        printf "."
    done
    echo ""
    ok "Backend ready (${waited}s)"
}

# ─── Shared Dev Virtualenv ─────────────────────────────────────────────────
# A single project-local venv at backend/.venv-dev hosts the dev tools listed
# in backend/requirements-dev.txt. Both `lint` (ruff) and `security` (bandit,
# pip-audit) source this; keep it in lib.sh so there is exactly one copy.

DEV_VENV="${DIR}/backend/.venv-dev"

# Ensure the dev venv exists and contains the dev tools. Idempotent and fast:
# once the binaries are present this is a no-op.
_ensure_dev_venv() {
    if [ -x "${DEV_VENV}/bin/ruff" ] && [ -x "${DEV_VENV}/bin/bandit" ] && [ -x "${DEV_VENV}/bin/pip-audit" ]; then
        return 0
    fi

    log_warn "Dev tools not found; creating isolated venv at ${DEV_VENV}..."
    python3 -m venv "$DEV_VENV"
    "$DEV_VENV/bin/pip" install -q --upgrade pip
    "$DEV_VENV/bin/pip" install -q -r "$DIR/backend/requirements-dev.txt"

    if [ ! -x "${DEV_VENV}/bin/ruff" ] || [ ! -x "${DEV_VENV}/bin/bandit" ] || [ ! -x "${DEV_VENV}/bin/pip-audit" ]; then
        die "Failed to install dev tools. Install manually or check network access."
    fi
}

# Resolve a Python dev tool, preferring a global install and falling back to
# the shared dev venv. Prints the absolute path of the binary on stdout.
_ensure_venv_tool() {
    local tool_name="$1"

    if command -v "$tool_name" > /dev/null 2>&1; then
        command -v "$tool_name"
        return 0
    fi

    _ensure_dev_venv
    echo "${DEV_VENV}/bin/${tool_name}"
}

# ─── Version String ─────────────────────────────────────────────────────────
# Resolve the NukeLab version string. Preference order:
#   1. $DIR/VERSION file (publishable artifact)
#   2. git describe --tags (e.g. v2.0, v2.0-3-gabc123)
#   3. hardcoded default (kept as a last-resort fallback)
#
# Lives in lib.sh (not scripts/manage.d/version.sh) because print_help() in
# nukelabctl calls it before any command module has been sourced.
_nukelab_version() {
    local version
    if [ -f "$DIR/VERSION" ]; then
        version=$(tr -d '[:space:]' < "$DIR/VERSION" 2> /dev/null || true)
        if [ -n "$version" ]; then
            echo "$version"
            return
        fi
    fi
    if command -v git > /dev/null 2>&1 && [ -d "$DIR/.git" ]; then
        # --tags only succeeds when at least one tag exists; --always is
        # intentionally omitted so a bare short-sha never masks the
        # hardcoded fallback default. The trailing `|| true` plus the `if`
        # guard both neutralize the ERR trap inherited via `set -E` so a
        # tag-less repo falls through to the v2.0 default instead of aborting.
        if version=$(cd "$DIR" && git describe --tags 2> /dev/null || true); then
            if [ -n "$version" ]; then
                echo "$version"
                return
            fi
        fi
    fi
    echo "v2.0"
}
