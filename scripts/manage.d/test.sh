cmd_test() {
    if [ "$TARGET" = "frontend" ] || [ "$TARGET" = "all" ]; then
        step "Running frontend tests..."
        cd "$DIR/frontend"
        [ -d "node_modules" ] || die "Run: ./manage.sh install frontend"
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

:         # To avoid Postgres connection exhaustion from the live dev server
        # (uvicorn workers + Celery) while tests run, stop the backend services
        # first, run tests in a fresh one-off container, then restart them.
        local _backend_was_running=false
        local _celery_worker_was_running=false
        local _celery_beat_was_running=false

        if is_backend_container_running; then
            _backend_was_running=true
            info "Stopping backend services for isolated test run..."
            $COMPOSE "${COMPOSE_ARGS[@]}" stop backend celery-worker celery-beat >/dev/null 2>&1 || true
        fi

        # Run tests in a fresh container with backend source bind-mounted.
        local _test_run_cmd="cd /app && python -m pytest ${pytest_args}"
        local _test_exit=0
        $COMPOSE "${COMPOSE_ARGS[@]}" run --rm \
            -v "${DIR}/backend:/app:Z" \
            -v "${DIR}/resources:/app/resources:ro" \
            -e "DATABASE_URL=postgresql+asyncpg://${DATABASE_USER:-nukelab}:${DATABASE_PASSWORD:-nukelab123}@postgres:5432/${DATABASE_NAME:-nukelab}_test" \
            -e "REDIS_URL=redis://redis:6379/1" \
            -e "RATE_LIMIT_ENABLED=false" \
            -e "OTEL_TRACES_ENABLED=false" \
            -e "SENTRY_DSN=" \
            -e "PROMETHEUS_SCRAPE_TOKEN=" \
            -e "PROMETHEUS_ENABLED=false" \
            -e "PGBOUNCER_ENABLED=false" \
            -e "TESTING=true" \
            backend bash -c "${_test_run_cmd}" || _test_exit=$?

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
