cmd_remove() {
    step "Removing containers..."

    local _services
    _services=$(_backend_services)

    if [ "$TARGET" = "frontend" ] || [ "$TARGET" = "all" ]; then
        kill_frontend
        $COMPOSE "${COMPOSE_ARGS[@]}" rm -f frontend 2>/dev/null || true
        ok "Frontend container removed"
    fi

    if [ "$TARGET" = "backend" ] || [ "$TARGET" = "all" ]; then
        $COMPOSE "${COMPOSE_ARGS[@]}" rm -f $_services 2>/dev/null || true
        _stop_orphan_if_unmanaged nukelab-pgbouncer
        if ! _has_overlay "compose.pgbouncer.yml"; then
            local _cmd="podman"
            [ "$CONTAINER_ENGINE" = "docker" ] && _cmd="docker"
            $_cmd rm -f nukelab-pgbouncer > /dev/null 2>&1 || true
        fi
        ok "Backend containers removed"
    fi
}
