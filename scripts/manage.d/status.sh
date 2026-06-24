cmd_status() {
    step "Container Status"
    $COMPOSE "${COMPOSE_ARGS[@]}" ps

    echo ""
    if is_frontend_running; then
        ok "Frontend dev: ${CYAN}http://localhost:5173${RESET} ${DIM}(PID: $(cat "$FRONTEND_PID_FILE"))${RESET}"
    else
        info "Frontend dev: ${DIM}not running${RESET}"
    fi
}
