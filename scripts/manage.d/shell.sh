cmd_shell() {
    local service="${TARGET:-backend}"
    if [[ "$service" = "all" ]]; then
        service="backend"
    fi

    step "Opening shell in ${BOLD}$service${RESET}..."

    case "$service" in
        backend)
            $COMPOSE "${COMPOSE_ARGS[@]}" exec backend /bin/bash || \
            $COMPOSE "${COMPOSE_ARGS[@]}" exec backend /bin/sh
            ;;
        postgres)
            $COMPOSE "${COMPOSE_ARGS[@]}" exec postgres psql -U "${DATABASE_USER:-nukelab}" -d "${DATABASE_NAME:-nukelab}"
            ;;
        redis)
            $COMPOSE "${COMPOSE_ARGS[@]}" exec redis redis-cli
            ;;
        frontend)
            $COMPOSE "${COMPOSE_ARGS[@]}" exec frontend /bin/sh
            ;;
        *)
            $COMPOSE "${COMPOSE_ARGS[@]}" exec "$service" /bin/sh
            ;;
    esac
}
