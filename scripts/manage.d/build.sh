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

help_build() {
    cat <<-EOF
${BOLD}Usage:${RESET} ./manage.sh build [target]

Build container images.

${BOLD}Targets:${RESET} backend | frontend | all

${BOLD}Examples:${RESET}
  ./manage.sh build
  ./manage.sh build backend
  ./manage.sh build frontend
EOF
}

