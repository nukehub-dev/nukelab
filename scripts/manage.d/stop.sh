#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Default values for stop options.
STOP_TIMEOUT=10
STOP_SERVERS=false

help_stop() {
    cat <<- EOF
${BOLD}Usage:${RESET} ./nukelabctl stop [target] [options]

Stop running containers.

${BOLD}Targets:${RESET}
  backend    Stop backend services
  frontend   Stop the frontend dev server (dev mode) or container
  all        Stop everything ${DIM}(default)${RESET}

${BOLD}Options:${RESET}
  --include-servers   Also stop spawned user server containers (nukelab-server-*)
  --timeout N, -t N   Seconds to wait before killing a container ${DIM}(default: 10)${RESET}
  --help, -h          Show this help

${BOLD}Examples:${RESET}
  ./nukelabctl stop
  ./nukelabctl stop backend
  ./nukelabctl stop backend --timeout 5
  ./nukelabctl stop --include-servers
EOF
}

parse_stop_args() {
    while [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; do
        case "${EXTRA_ARGS[0]}" in
            --include-servers)
                STOP_SERVERS=true
                EXTRA_ARGS=("${EXTRA_ARGS[@]:1}")
                ;;
            --timeout | -t)
                if [[ ${#EXTRA_ARGS[@]} -lt 2 ]]; then
                    die "Option ${EXTRA_ARGS[0]} requires a value"
                fi
                STOP_TIMEOUT="${EXTRA_ARGS[1]}"
                EXTRA_ARGS=("${EXTRA_ARGS[@]:2}")
                ;;
            --help | -h)
                help_stop
                exit 0
                ;;
            --*)
                die "Unknown option for stop: ${EXTRA_ARGS[0]}"
                ;;
            *)
                if [[ -z "${TARGET:-}" || "$TARGET" == "all" ]]; then
                    TARGET="${EXTRA_ARGS[0]}"
                    EXTRA_ARGS=("${EXTRA_ARGS[@]:1}")
                else
                    die "Unexpected argument: ${EXTRA_ARGS[0]}"
                fi
                ;;
        esac
    done

    if ! [[ "$STOP_TIMEOUT" =~ ^[0-9]+$ ]]; then
        die "--timeout requires a non-negative integer, got: $STOP_TIMEOUT"
    fi
}

cmd_stop() {
    step "Stopping services..."

    local _services
    _services=$(_backend_services)

    if [ "$TARGET" = "frontend" ] || [ "$TARGET" = "all" ]; then
        kill_frontend
        $COMPOSE "${COMPOSE_ARGS[@]}" stop -t "$STOP_TIMEOUT" frontend > /dev/null 2>&1 || true
    fi

    if [ "$TARGET" = "backend" ] || [ "$TARGET" = "all" ]; then
        $COMPOSE "${COMPOSE_ARGS[@]}" stop -t "$STOP_TIMEOUT" $_services > /dev/null 2>&1 || true
    fi

    # PgBouncer and tracing may have been started with an overlay but the env
    # var is not set now (e.g. user forgot PGBOUNCER_ENABLED=true or
    # TRACING_ENABLED=true). Stop them directly so restarting containers do not
    # block shutdown or keep consuming ports.
    _stop_orphan_if_unmanaged "compose.pgbouncer.yml" nukelab-pgbouncer
    _stop_orphan_if_unmanaged "compose.tracing.yml" nukelab-otel-collector
    _stop_orphan_if_unmanaged "compose.tracing.yml" nukelab-jaeger

    # Stop spawned user server containers on request so they don't become ghost
    # containers after the platform stack is down.
    if $STOP_SERVERS; then
        local _server_ids
        _server_ids=$($CONTAINER_ENGINE ps -q --filter name=^nukelab-server- 2> /dev/null) || true
        if [ -n "$_server_ids" ]; then
            log "Stopping spawned server containers..."
            $CONTAINER_ENGINE stop -t "$STOP_TIMEOUT" $_server_ids > /dev/null 2>&1 || true
        fi
    fi

    ok "Stopped"
}
