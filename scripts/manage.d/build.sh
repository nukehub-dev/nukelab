cmd_build() {
    setup_cpu_lib_volume

    step "Building..."

    if [ "$TARGET" = "backend" ] || [ "$TARGET" = "all" ]; then
        log "Building backend containers..."
        _run_quiet_unless_verbose $COMPOSE "${COMPOSE_ARGS[@]}" build backend celery-worker celery-beat
        log "Building backend test container..."
        _run_quiet_unless_verbose $COMPOSE --profile test "${COMPOSE_ARGS[@]}" build backend-test
    fi

    if [ "$TARGET" = "frontend" ] || [ "$TARGET" = "all" ]; then
        log "Building frontend container..."
        _run_quiet_unless_verbose $COMPOSE "${COMPOSE_ARGS[@]}" build frontend
    fi

    ok "Build complete"
}

help_build() {
    cat <<-EOF
${BOLD}Usage:${RESET} ./nukelabctl build [target]

Build container images.

${BOLD}Targets:${RESET} backend | frontend | all

${BOLD}Examples:${RESET}
  ./nukelabctl build
  ./nukelabctl build backend
  ./nukelabctl build frontend
EOF
}

