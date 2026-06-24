#!/bin/bash
# NukeLab shared helper library for management scripts.
# Source this from any script that needs environment loading or container-engine
# detection so the logic stays in one place.

# Provide plain fallbacks if the sourcing script does not define these helpers.
if ! type -t info | grep -q function 2>/dev/null; then
    info() { echo "ℹ  $*" >&2; }
fi
if ! type -t warn | grep -q function 2>/dev/null; then
    warn() { echo "⚠  $*" >&2; }
fi
if ! type -t die | grep -q function 2>/dev/null; then
    die() { echo "✗ $*" >&2; exit 1; }
fi

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
            export "$cleaned" 2>/dev/null || true
        fi
    done < "$env_file"
}

# Usage: init_env [dev_mode]
# Loads .env as base defaults, then .env.development when dev_mode is true or
# when .env is missing and .env.development exists.
init_env() {
    local dev_mode="${1:-false}"

    # Always load .env as base defaults
    if [ -f .env ]; then
        load_env_file .env
    fi

    # In dev mode, overlay .env.development on top so dev values win.
    # Also use .env.development as a fallback when no .env exists.
    if $dev_mode && [ -f .env.development ]; then
        load_env_file .env.development
    elif [ ! -f .env ] && [ -f .env.development ]; then
        load_env_file .env.development
    elif [ ! -f .env ] && [ ! -f .env.development ]; then
        die "No environment file found.\n\n  cp .env.example .env.development"
    fi
}

# ─── Container Engine ─────────────────────────────────────────────────────-
# Usage: detect_engine
# Sets CONTAINER_ENGINE (podman|docker) and COMPOSE (podman-compose,
# docker-compose, or "<engine> compose").
detect_engine() {
    if command -v podman > /dev/null 2>&1; then
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

# Usage: setup_podman_socket
# When running under Podman, ensure DOCKER_SOCKET points to the active API socket.
setup_podman_socket() {
    [ "$CONTAINER_ENGINE" != "podman" ] && return

    # If DOCKER_SOCKET is set but doesn't exist, override it
    if [ -n "${DOCKER_SOCKET:-}" ] && [ ! -S "$DOCKER_SOCKET" ]; then
        warn "DOCKER_SOCKET=$DOCKER_SOCKET not found, auto-detecting..."
        unset DOCKER_SOCKET
    fi

    # Auto-detect if not set
    if [ -z "${DOCKER_SOCKET:-}" ]; then
        SOCK=$(podman info --format '{{.Host.RemoteSocket.Path}}' 2>/dev/null || true)
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
is_frontend_running() {
    [ -f "$FRONTEND_PID_FILE" ] && kill -0 "$(cat "$FRONTEND_PID_FILE")" 2>/dev/null
}

kill_frontend() {
    if is_frontend_running; then
        local pid=$(cat "$FRONTEND_PID_FILE")
        log "Stopping frontend (PID: $pid)..."
        kill "$pid" 2>/dev/null || true
        rm -f "$FRONTEND_PID_FILE"
        ok "Frontend stopped"
    fi
}

_container_exists() {
    local name="$1"
    local _cmd="podman"
    [ "$CONTAINER_ENGINE" = "docker" ] && _cmd="docker"
    $_cmd ps -a --filter "name=^${name}$" --format "{{.Names}}" 2>/dev/null | grep -qx "$name"
}

_container_running() {
    local name="$1"
    local _cmd="podman"
    [ "$CONTAINER_ENGINE" = "docker" ] && _cmd="docker"
    $_cmd ps --filter "name=^${name}$" --filter "status=running" --format "{{.Names}}" 2>/dev/null | grep -qx "$name"
}

_stop_orphan_container() {
    local name="$1"
    local _cmd="podman"
    [ "$CONTAINER_ENGINE" = "docker" ] && _cmd="docker"
    if $_cmd ps --filter "name=^${name}$" --filter "status=running" --format "{{.Names}}" 2>/dev/null | grep -qx "$name"; then
        log "Stopping orphan container ${BOLD}$name${RESET}..."
        $_cmd stop -t 10 "$name" > /dev/null 2>&1 || true
    fi
}

# Stop a container only when it is not already managed through compose.
_stop_orphan_if_unmanaged() {
    local name="$1"
    # If the current compose configuration already includes PgBouncer,
    # the regular compose stop/rm will handle it; no orphan cleanup needed.
    if _has_overlay "compose.pgbouncer.yml"; then
        return
    fi
    _stop_orphan_container "$name"
}

is_backend_container_running() {
    # Check via compose first (respects selected overlays), but fall back to
    # checking the container engine directly. This lets `manage.sh test backend`
    # work even when the stack was started with a slightly different set of
    # overlays (e.g. --dev) because the container name stays the same.
    if $COMPOSE "${COMPOSE_ARGS[@]}" ps 2>/dev/null | grep -q 'Up .*nukelab-backend'; then
        return 0
    fi

    local _container_cmd="podman"
    if [ "$CONTAINER_ENGINE" = "docker" ]; then
        _container_cmd="docker"
    fi
    $_container_cmd ps --filter "name=^nukelab-backend$" --filter "status=running" --format "{{.Names}}" 2>/dev/null | grep -qx "nukelab-backend"
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
    # Print the list of backend services, including PgBouncer and monitoring when enabled.
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
    echo "$services"
}

_stop_dev_stack() {
    # Dev-mode Ctrl+C handler: stop Vite and all backend/monitoring containers.
    echo ""
    step "Shutting down..."
    kill_frontend
    $COMPOSE "${COMPOSE_ARGS[@]}" stop $(_backend_services) > /dev/null 2>&1 || true
    _stop_orphan_if_unmanaged nukelab-pgbouncer
    _release_lock 2>/dev/null || true
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
    if ! $CONTAINER_ENGINE image exists "$build_image" 2>/dev/null; then
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

wait_for_backend() {
    local url="${APP_URL:-http://localhost:8080}/api/health"
    local waited=0
    step "Waiting for backend..."
    while ! curl -sf "$url" > /dev/null 2>&1; do
        sleep 2
        waited=$((waited + 2))
        [ "$waited" -ge 60 ] && { warn "Timeout, continuing..."; return 1; }
        printf "."
    done
    echo ""
    ok "Backend ready (${waited}s)"
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

# ─── Pre-flight Validation ─────────────────────────────────────────────────
# Usage: preflight_checks
# Performs a set of cheap, host-side sanity checks before mutating commands
# such as start/build/update/test. Prints actionable errors and exits on
# failure. Set SKIP_PORT_CHECK=true to bypass the port checks.

_preflight_port_in_use() {
    local port="$1"
    if command -v ss >/dev/null 2>&1; then
        ss -tln 2>/dev/null | grep -Eq ":${port}[[:space:]]" && return 0
    elif command -v netstat >/dev/null 2>&1; then
        netstat -tln 2>/dev/null | grep -Eq ":${port}[[:space:]]" && return 0
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

# ─── Concurrency Lock ──────────────────────────────────────────────────────
# Prevents two manage.sh invocations from running conflicting operations at the
# same time. The lock file stores the PID and command of the holding process.

LOCK_DIR="${XDG_RUNTIME_DIR:-$HOME/.local/share}/nukelab"
LOCK_FILE="$LOCK_DIR/manage.lock"

_acquire_lock() {
    mkdir -p "$LOCK_DIR"
    if [ -f "$LOCK_FILE" ]; then
        local other_pid
        other_pid=$(awk 'NR==1' "$LOCK_FILE" 2>/dev/null || true)
        if [ -n "$other_pid" ] && kill -0 "$other_pid" 2>/dev/null; then
            local other_cmd
            other_cmd=$(sed -n '2p' "$LOCK_FILE" 2>/dev/null || true)
            die "Another manage.sh process is already running (PID $other_pid, command: ${other_cmd:-unknown}).\nWait for it to finish or remove $LOCK_FILE if it crashed."
        fi
        warn "Stale lock found (PID ${other_pid:-unknown}). Removing..."
        rm -f "$LOCK_FILE"
    fi
    echo "$$" > "$LOCK_FILE"
    echo "$CMD ${TARGET:-}" >> "$LOCK_FILE"
    trap '_release_lock' EXIT INT TERM
}

_release_lock() {
    if [ -f "$LOCK_FILE" ] && [ "$(awk 'NR==1' "$LOCK_FILE" 2>/dev/null || true)" = "$$" ]; then
        rm -f "$LOCK_FILE"
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
    if ! command -v "$CONTAINER_ENGINE" >/dev/null 2>&1; then
        die "Container engine '$CONTAINER_ENGINE' not found"
    fi
    if ! "$CONTAINER_ENGINE" info >/dev/null 2>&1; then
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
    if [ "${APP_ENV:-development}" = "production" ]; then
        if [ -z "${VOLUME_STORAGE_PATH:-}" ]; then
            die "VOLUME_STORAGE_PATH is required in production.\nSet it to the host path where container volumes are stored."
        fi
        if [ ! -d "$VOLUME_STORAGE_PATH" ]; then
            die "VOLUME_STORAGE_PATH does not exist: $VOLUME_STORAGE_PATH"
        fi
    else
        if [ -n "${VOLUME_STORAGE_PATH:-}" ] && [ ! -d "$VOLUME_STORAGE_PATH" ]; then
            warn "VOLUME_STORAGE_PATH does not exist: $VOLUME_STORAGE_PATH"
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

