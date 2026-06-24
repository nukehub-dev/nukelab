cmd_exec() {
    local service="${TARGET:-backend}"
    if [[ "$service" = "all" ]]; then
        service="backend"
    fi

    if [ ${#EXTRA_ARGS[@]} -eq 0 ]; then
        die "Usage: ./manage.sh exec <service> <command>\nExample: ./manage.sh exec backend ls -la"
    fi

    $COMPOSE "${COMPOSE_ARGS[@]}" exec "$service" "${EXTRA_ARGS[@]}"
}
