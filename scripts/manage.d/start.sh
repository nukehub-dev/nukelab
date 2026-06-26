# Default values for start options.
START_BUILD=true
START_WAIT=true

help_start() {
    cat <<-EOF
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
            --help|-h)
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
        "$DIR/scripts/generate-alertmanager-config.sh" "$_env_file" >/dev/null
    fi
    if [ -f "$DIR/scripts/generate-prometheus-config.sh" ]; then
        "$DIR/scripts/generate-prometheus-config.sh" "$_env_file" >/dev/null
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
            local _up_args=(-d)
            if ! $START_BUILD; then
                _up_args+=(--no-build)
            fi
            # Suppress noisy compose warnings about containers that do not
            # yet exist; they are harmless on a fresh start/restart.
            if $VERBOSE; then
                _run_quiet_unless_verbose $COMPOSE "${COMPOSE_ARGS[@]}" up "${_up_args[@]}" $_dev_backend_services
            else
                local _up_out
                _up_out=$(mktemp)
                if ! $COMPOSE "${COMPOSE_ARGS[@]}" up "${_up_args[@]}" $_dev_backend_services > "$_up_out" 2>&1; then
                    cat "$_up_out" >&2
                    rm -f "$_up_out"
                    return 1
                fi
                rm -f "$_up_out"
            fi
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

        trap '_stop_dev_stack' INT TERM
        wait
    else
        step "Starting production stack..."

        local _prod_backend_services
        _prod_backend_services=$(_backend_services)

        local _up_args=(-d)
        if ! $START_BUILD; then
            _up_args+=(--no-build)
        fi

        if [ "$TARGET" = "all" ]; then
            # Start backend services first, then the frontend container.
            # Doing this in two calls lets podman-compose reconcile the
            # backend services without the frontend container confusing it,
            # while we suppress harmless "no container with name ..." warnings.
            log "Starting backend services..."
            if $VERBOSE; then
                _run_quiet_unless_verbose $COMPOSE "${COMPOSE_ARGS[@]}" up "${_up_args[@]}" $_prod_backend_services
            else
                local _up_out
                _up_out=$(mktemp)
                if ! $COMPOSE "${COMPOSE_ARGS[@]}" up "${_up_args[@]}" $_prod_backend_services > "$_up_out" 2>&1; then
                    cat "$_up_out" >&2
                    rm -f "$_up_out"
                    return 1
                fi
                rm -f "$_up_out"
            fi

            log "Starting frontend container..."
            _run_quiet_unless_verbose $COMPOSE "${COMPOSE_ARGS[@]}" up "${_up_args[@]}" frontend
        elif [ "$TARGET" = "backend" ]; then
            log "Starting backend services..."
            _run_quiet_unless_verbose $COMPOSE "${COMPOSE_ARGS[@]}" up "${_up_args[@]}" $_prod_backend_services
        elif [ "$TARGET" = "frontend" ]; then
            log "Starting frontend container..."
            _run_quiet_unless_verbose $COMPOSE "${COMPOSE_ARGS[@]}" up "${_up_args[@]}" frontend
        fi

        persist_state

        ok "Stack running!"
        echo -e "  URL: ${CYAN}http://localhost:8080${RESET}"
        echo -e "  API: ${CYAN}http://localhost:8080/api${RESET}"
    fi
}
