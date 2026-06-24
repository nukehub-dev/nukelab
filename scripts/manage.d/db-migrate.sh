cmd_db_migrate() {
    step "Running database migrations..."

    if is_backend_container_running; then
        # Backend is running in containers, run migrations there
        $COMPOSE "${COMPOSE_ARGS[@]}" exec backend alembic upgrade head
    else
        die "Backend not running. Start it first:\n  ./nukelabctl start backend"
    fi

    ok "Migrations applied"
}

help_db_migrate() {
    cat <<-EOF
${BOLD}Usage:${RESET} ./nukelabctl db-migrate

Run Alembic database migrations inside the backend container.

${BOLD}Examples:${RESET}
  ./nukelabctl db-migrate
EOF
}

