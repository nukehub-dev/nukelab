cmd_db_migrate() {
    step "Running database migrations..."

    if is_backend_container_running; then
        # Backend is running in containers, run migrations there
        $COMPOSE "${COMPOSE_ARGS[@]}" exec backend alembic upgrade head
    else
        die "Backend not running. Start it first:\n  ./manage.sh start backend"
    fi

    ok "Migrations applied"
}
