cmd_reset() {
    step "${RED}${BOLD}WARNING:${RESET} This deletes ALL data and containers!"
    read -rp "Type 'yes' to confirm: " confirm
    [[ "$confirm" = "yes" ]] || { info "Aborted."; exit 0; }

    log "Stopping everything..."
    kill_frontend
    if $COMPOSE "${COMPOSE_ARGS[@]}" down -v --remove-orphans; then
        log_debug "compose down completed"
    else
        warn "compose down returned an error; continuing with manual volume cleanup"
    fi
    if $CONTAINER_ENGINE volume rm nukelab-postgres-data nukelab-letsencrypt 2>/dev/null; then
        log_debug "Named volumes removed"
    else
        log_debug "Named volumes were already removed or do not exist"
    fi
    clear_state
    ok "Reset complete"
}

help_reset() {
    cat <<-EOF
${BOLD}Usage:${RESET} ./manage.sh reset

⚠️  Delete ALL data, containers, and volumes. Requires confirmation.

${BOLD}Examples:${RESET}
  ./manage.sh reset
EOF
}

