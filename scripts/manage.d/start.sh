# Default values for start options.
START_BUILD=true
START_WAIT=true

help_start() {
    cat <<-EOF
${BOLD}Usage:${RESET} ./manage.sh start [target] [options]

Start the NukeLab stack.

${BOLD}Targets:${RESET}
  backend    Start backend services ${DIM}(default if omitted)${RESET}
  frontend   Start frontend container (or Vite dev server with --dev)
  all        Start everything

${BOLD}Options:${RESET}
  --dev, -d       Development mode: backend containers + local Vite dev server
  --no-build      Skip building images before starting
  --no-wait       Do not wait for the backend health check
  --overlay FILE  Add a compose overlay file (repeatable)
  --help, -h      Show this help

${BOLD}Examples:${RESET}
  ./manage.sh start
  ./manage.sh start --dev
  ./manage.sh start backend --no-build
  PGBOUNCER_ENABLED=true ./manage.sh start
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

        $COMPOSE "${COMPOSE_ARGS[@]}" stop frontend > /dev/null 2>&1 || true

        local _dev_backend_services
        _dev_backend_services=$(_backend_services)

        if [ "$TARGET" = "backend" ] || [ "$TARGET" = "all" ]; then
            log "Starting backend containers..."
            local _up_args=(-d)
            if ! $START_BUILD; then
                _up_args+=(--no-build)
            fi
            $COMPOSE "${COMPOSE_ARGS[@]}" up "${_up_args[@]}" $_dev_backend_services > /dev/null
            if $START_WAIT; then
                wait_for_backend || true
            fi
        fi

        if [ "$TARGET" = "frontend" ] || [ "$TARGET" = "all" ]; then
            command -v npm > /dev/null 2>&1 || die "npm not found"
            [ -d "$DIR/frontend/node_modules" ] || die "Run: ./manage.sh install frontend"
            log "Starting Vite dev server..."

            cd "$DIR/frontend"
            npm run dev &
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

        if [ "$TARGET" = "backend" ] || [ "$TARGET" = "all" ]; then
            log "Starting backend services..."
            local _up_args=(-d)
            if ! $START_BUILD; then
                _up_args+=(--no-build)
            fi
            $COMPOSE "${COMPOSE_ARGS[@]}" up "${_up_args[@]}" $_prod_backend_services > /dev/null
        fi

        if [ "$TARGET" = "frontend" ] || [ "$TARGET" = "all" ]; then
            log "Starting frontend container..."
            local _up_args=(-d)
            if ! $START_BUILD; then
                _up_args+=(--no-build)
            fi
            $COMPOSE "${COMPOSE_ARGS[@]}" up "${_up_args[@]}" frontend > /dev/null
        fi

        persist_state

        ok "Stack running!"
        echo -e "  URL: ${CYAN}http://localhost:8080${RESET}"
        echo -e "  API: ${CYAN}http://localhost:8080/api${RESET}"
    fi
}
