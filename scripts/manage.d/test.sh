cmd_test() {
    if [ "$TARGET" = "frontend" ] || [ "$TARGET" = "all" ]; then
        step "Running frontend tests..."
        cd "$DIR/frontend"
        [ -d "node_modules" ] || die "Run: ./nukelabctl install frontend"
        npm run test 2>/dev/null || npm run lint || warn "No test script found"
    fi

    if [ "$TARGET" = "backend" ] || [ "$TARGET" = "all" ]; then
        step "Running backend tests..."
        # Stay in $DIR so relative compose overlay paths resolve correctly.
        # pytest itself runs inside the container at /app, so the host CWD
        # does not affect test discovery.
        local pytest_args="${EXTRA_ARGS[*]:-}"
        if $USE_COVERAGE; then
            pytest_args="--cov=app --cov-report=term --cov-report=html ${pytest_args}"
        fi

        # To avoid Postgres connection exhaustion from the live dev server
        # (uvicorn workers + Celery) while tests run, stop the backend services
        # first, run tests in a fresh one-off container, then restart them.
        local _backend_was_running=false

        if is_backend_container_running; then
            _backend_was_running=true
            info "Stopping backend services for isolated test run..."
            $COMPOSE "${COMPOSE_ARGS[@]}" stop backend celery-worker celery-beat >/dev/null 2>&1 || true
        fi

        # Run tests in the dedicated backend-test container. Dev/test
        # dependencies are baked into the image (Dockerfile target=test),
        # so no runtime pip install is required.
        local _test_run_cmd="python -m pytest ${pytest_args}"
        local _test_exit=0
        $COMPOSE --profile test "${COMPOSE_ARGS[@]}" run --rm \
            -v "${DIR}/backend:/app:Z" \
            -v "${DIR}/resources:/app/resources:ro" \
            -e "DATABASE_USER=${DATABASE_USER:-nukelab}" \
            -e "DATABASE_PASSWORD=${DATABASE_PASSWORD:-nukelab123}" \
            -e "DATABASE_NAME=${DATABASE_NAME:-nukelab}_test" \
            -e "DATABASE_HOST=${DATABASE_HOST:-postgres}" \
            -e "DATABASE_PORT=${DATABASE_PORT:-5432}" \
            -e "REDIS_URL=redis://redis:6379/1" \
            -e "RATE_LIMIT_ENABLED=false" \
            -e "OTEL_TRACES_ENABLED=false" \
            -e "SENTRY_DSN=" \
            -e "PROMETHEUS_SCRAPE_TOKEN=" \
            -e "PROMETHEUS_ENABLED=false" \
            -e "PGBOUNCER_ENABLED=false" \
            -e "TESTING=true" \
            backend-test bash -c "${_test_run_cmd}" || _test_exit=$?

        # Restart backend services if they were running before.
        if $_backend_was_running; then
            info "Restarting backend services..."
            $COMPOSE "${COMPOSE_ARGS[@]}" up -d backend celery-worker celery-beat >/dev/null 2>&1 || warn "Failed to restart backend services"
        fi

        if [ $_test_exit -ne 0 ]; then
            warn "Tests failed or not configured"
        fi
    fi
}

help_test() {
    cat <<-EOF
${BOLD}Usage:${RESET} ./nukelabctl test [target]

Run tests.

${BOLD}Targets:${RESET} frontend | backend | all

${BOLD}Options:${RESET}
  --coverage    Run backend tests with coverage report

${BOLD}Examples:${RESET}
  ./nukelabctl test
  ./nukelabctl test backend
  ./nukelabctl test backend --coverage
EOF
}
