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
