cmd_reset() {
    step "${RED}${BOLD}WARNING:${RESET} This deletes ALL data and containers!"
    read -rp "Type 'yes' to confirm: " confirm
    [[ "$confirm" = "yes" ]] || { info "Aborted."; exit 0; }

    log "Stopping everything..."
    kill_frontend
    $COMPOSE "${COMPOSE_ARGS[@]}" down -v --remove-orphans 2>/dev/null || true
    $CONTAINER_ENGINE volume rm nukelab-postgres-data nukelab-letsencrypt 2>/dev/null || true
    clear_state
    ok "Reset complete"
}
