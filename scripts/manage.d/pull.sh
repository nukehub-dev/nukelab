cmd_pull() {
    step "Pulling latest images..."
    $COMPOSE "${COMPOSE_ARGS[@]}" pull
    ok "Images pulled"
}
