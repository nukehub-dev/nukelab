cmd_update() {
    step "Updating NukeLab..."

    log "Pulling latest images..."
    _run_quiet_unless_verbose $COMPOSE "${COMPOSE_ARGS[@]}" pull

    log "Rebuilding containers..."
    _run_quiet_unless_verbose $COMPOSE "${COMPOSE_ARGS[@]}" build --no-cache

    ok "Update complete! Run './manage.sh restart' to apply changes."
}

help_update() {
    cat <<-EOF
${BOLD}Usage:${RESET} ./manage.sh update

Pull latest base images and rebuild all containers.

${BOLD}Examples:${RESET}
  ./manage.sh update
EOF
}

