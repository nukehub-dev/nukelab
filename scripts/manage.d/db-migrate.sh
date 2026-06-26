cmd_db_migrate() {
    step "Running database migrations..."

    if is_backend_container_running; then
        # Backend is running in containers, run migrations there.
        # Force a direct Postgres URL even if DATABASE_URL points to PgBouncer;
        # DDL must not go through the connection pooler.
        local direct_url
        direct_url=$(_direct_database_url)
        if [[ "${DATABASE_HOST:-postgres}" == "pgbouncer" ]] || [[ "${DATABASE_PORT:-5432}" == "6432" ]]; then
            info "Routing migration through direct Postgres connection"
        fi
        _run_quiet_unless_verbose $COMPOSE "${COMPOSE_ARGS[@]}" exec -e "DATABASE_URL=$direct_url" backend alembic upgrade head
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

