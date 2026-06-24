cmd_stop() {
    step "Stopping services..."

    local _services
    _services=$(_backend_services)

    if [ "$TARGET" = "frontend" ] || [ "$TARGET" = "all" ]; then
        kill_frontend
        $COMPOSE "${COMPOSE_ARGS[@]}" stop frontend > /dev/null 2>&1 || true
    fi

    if [ "$TARGET" = "backend" ] || [ "$TARGET" = "all" ]; then
        $COMPOSE "${COMPOSE_ARGS[@]}" stop $_services > /dev/null 2>&1 || true
    fi

    # PgBouncer may have been started with the overlay but the env var is not
    # set now (e.g. user forgot PGBOUNCER_ENABLED=true). Stop it directly so a
    # restarting container does not block shutdown or keep consuming ports.
    _stop_orphan_if_unmanaged nukelab-pgbouncer

    ok "Stopped"
}
