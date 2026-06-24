cmd_build() {
    setup_cpu_lib_volume

    step "Building..."

    if [ "$TARGET" = "backend" ] || [ "$TARGET" = "all" ]; then
        log "Building backend containers..."
        $COMPOSE "${COMPOSE_ARGS[@]}" build backend celery-worker celery-beat
    fi

    if [ "$TARGET" = "frontend" ] || [ "$TARGET" = "all" ]; then
        log "Building frontend container..."
        $COMPOSE "${COMPOSE_ARGS[@]}" build frontend
    fi

    ok "Build complete"
}
