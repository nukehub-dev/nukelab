cmd_update() {
    step "Updating NukeLab..."

    log "Pulling latest images..."
    $COMPOSE "${COMPOSE_ARGS[@]}" pull

    log "Rebuilding containers..."
    $COMPOSE "${COMPOSE_ARGS[@]}" build --no-cache

    ok "Update complete! Run './manage.sh restart' to apply changes."
}
