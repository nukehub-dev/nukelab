#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Default values for start options.
START_BUILD=true
START_WAIT=true

help_start() {
    cat <<- EOF
${BOLD}Usage:${RESET} ./nukelabctl start [target] [options]

Start the NukeLab stack.

${BOLD}Targets:${RESET}
  backend    Start backend services ${DIM}(default if omitted)${RESET}
  frontend   Start frontend container
  all        Start everything

${BOLD}Options:${RESET}
  --no-build      Skip building images before starting
  --no-wait       Do not wait for the backend health check
  --overlay FILE  Add a compose overlay file (repeatable)
  --help, -h      Show this help

${BOLD}Examples:${RESET}
  ./nukelabctl start
  ./nukelabctl start backend --no-build
  PGBOUNCER_ENABLED=true ./nukelabctl start
EOF
}

parse_start_args() {
    while [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; do
        case "${EXTRA_ARGS[0]}" in
            --no-build)
                START_BUILD=false
                EXTRA_ARGS=("${EXTRA_ARGS[@]:1}")
                ;;
            --no-wait)
                START_WAIT=false
                EXTRA_ARGS=("${EXTRA_ARGS[@]:1}")
                ;;
            --help | -h)
                help_start
                exit 0
                ;;
            --*)
                die "Unknown option for start: ${EXTRA_ARGS[0]}"
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

    case "$TARGET" in
        backend | frontend | all) ;;
        *)
            die "Unknown target for start: $TARGET\nRun './nukelabctl start --help' for usage."
            ;;
    esac
}

cmd_start() {
    # Dev and prod share container names; only one may run at a time.
    _require_other_stack_stopped
    _warn_stale_containers

    setup_cpu_lib_volume

    # Generate dynamic config files from templates before compose reads them.
    local _env_file=".env"
    if $USE_DEV_MODE && [ -f ".env.development" ]; then
        _env_file=".env.development"
    fi
    if [ -f "$DIR/scripts/generate-alertmanager-config.sh" ]; then
        "$DIR/scripts/generate-alertmanager-config.sh" "$_env_file" > /dev/null
    fi
    if [ -f "$DIR/scripts/generate-prometheus-config.sh" ]; then
        "$DIR/scripts/generate-prometheus-config.sh" "$_env_file" > /dev/null
    fi

    if $USE_DEV_MODE; then
        step "Starting development stack..."

        # In dev mode, frontend runs on Vite dev server (port 5173)
        # This tells the backend where to redirect after OAuth login
        export FRONTEND_URL="${FRONTEND_URL:-http://localhost:5173}"
        info "FRONTEND_URL=$FRONTEND_URL"

        $COMPOSE "${COMPOSE_ARGS[@]}" stop frontend > /dev/null 2>&1 || log_debug "Frontend container was not running"

        local _dev_backend_services
        _dev_backend_services=$(_backend_services)

        if [ "$TARGET" = "backend" ] || [ "$TARGET" = "all" ]; then
            log "Starting backend containers..."
            # _backend_services returns a space-separated list; intentionally
            # unquoted so compose sees each service as a separate argument.
            # shellcheck disable=SC2086
            _start_compose_up $_dev_backend_services
            if $START_WAIT; then
                wait_for_backend || true
            fi
        fi

        if [ "$TARGET" = "frontend" ] || [ "$TARGET" = "all" ]; then
            command -v npm > /dev/null 2>&1 || die "npm not found"
            [ -d "$DIR/frontend/node_modules" ] || die "Run: ./nukelabctl install frontend"
            log "Starting Vite dev server..."

            # Start Vite in a subshell so the PID file points at the npm process.
            # kill_frontend walks child processes to ensure the dev server dies
            # cleanly when the user hits Ctrl+C or runs ./nukelabctl stop.
            (
                cd "$DIR/frontend"
                npm run dev
            ) &
            echo $! > "$FRONTEND_PID_FILE"
            ok "Frontend started on ${CYAN}http://localhost:5173${RESET}"
        fi

        echo ""
        ok "Development stack running!"
        echo -e "  Frontend: ${CYAN}http://localhost:5173${RESET} ${DIM}(Vite dev)${RESET}"
        echo -e "  API:      ${CYAN}http://localhost:8080/api${RESET}"
        echo -e "\n  ${YELLOW}Ctrl+C to stop${RESET}"

        persist_state

        # The start operation is done; the blocking wait below only idles
        # while the dev session runs. Release the manage lock so other
        # nukelabctl commands (logs, backup, stop, ...) work during it.
        _release_lock

        trap '_stop_dev_stack' INT TERM
        wait
    else
        step "Starting production stack..."

        local _prod_backend_services
        _prod_backend_services=$(_backend_services)

        if [ "$TARGET" = "all" ]; then
            # Start backend services first, then the frontend container.
            # Doing this in two calls lets podman-compose reconcile the
            # backend services without the frontend container confusing it.
            log "Starting backend services..."
            # Intentionally unquoted; see SC2086 note above.
            # shellcheck disable=SC2086
            _start_compose_up $_prod_backend_services
            if $START_WAIT; then
                wait_for_backend || true
            fi

            log "Starting frontend container..."
            _start_compose_up frontend
        elif [ "$TARGET" = "backend" ]; then
            log "Starting backend services..."
            # shellcheck disable=SC2086
            _start_compose_up $_prod_backend_services
            if $START_WAIT; then
                wait_for_backend || true
            fi
        elif [ "$TARGET" = "frontend" ]; then
            log "Starting frontend container..."
            _start_compose_up frontend
        fi

        persist_state

        ok "Stack running!"
        echo -e "  URL: ${CYAN}http://localhost:8080${RESET}"
        echo -e "  API: ${CYAN}http://localhost:8080/api${RESET}"
    fi
}
