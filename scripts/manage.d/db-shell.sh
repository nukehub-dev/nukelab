cmd_db_shell() {
    step "Opening database shell..."
    $COMPOSE "${COMPOSE_ARGS[@]}" exec postgres psql -U "${DATABASE_USER:-nukelab}" -d "${DATABASE_NAME:-nukelab}"
}
