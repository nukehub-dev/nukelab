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
            $COMPOSE "${COMPOSE_ARGS[@]}" up -d $_dev_backend_services > /dev/null
            wait_for_backend || true
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
            $COMPOSE "${COMPOSE_ARGS[@]}" up -d $_prod_backend_services > /dev/null
        fi

        if [ "$TARGET" = "frontend" ] || [ "$TARGET" = "all" ]; then
            log "Starting frontend container..."
            $COMPOSE "${COMPOSE_ARGS[@]}" up -d frontend > /dev/null
        fi

        persist_state

        ok "Stack running!"
        echo -e "  URL: ${CYAN}http://localhost:8080${RESET}"
        echo -e "  API: ${CYAN}http://localhost:8080/api${RESET}"
    fi
}
