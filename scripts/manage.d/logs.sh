cmd_logs() {
    local service="${TARGET:-}"

    # In dev mode, frontend runs locally via Vite, not container
    if $USE_DEV_MODE && [[ "$service" == "" || "$service" == "all" ]]; then
        log "Dev mode: frontend runs locally via Vite (check terminal for output)"
        service="traefik postgres redis backend celery-worker celery-beat"
    fi

    $COMPOSE "${COMPOSE_ARGS[@]}" logs -f ${service:-}
}
