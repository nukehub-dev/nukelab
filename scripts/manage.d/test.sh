#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

cmd_test() {
    # Collect per-suite results so every selected suite runs even when an
    # earlier one fails; the command exits non-zero at the end if any failed.
    local _failed_suites=()

    if [ "$TARGET" = "frontend" ] || [ "$TARGET" = "all" ]; then
        step "Running frontend tests..."
        cd "$DIR/frontend"
        [ -d "node_modules" ] || die "Run: ./nukelabctl install frontend"
        if ! npm run test:unit; then
            warn "Frontend unit tests failed"
            _failed_suites+=("frontend")
        fi
        # Return to $DIR so relative compose overlay paths resolve correctly
        # for the backend suite below.
        cd "$DIR"
    fi

    if [ "$TARGET" = "backend" ] || [ "$TARGET" = "all" ]; then
        step "Running backend tests..."
        # Stay in $DIR so relative compose overlay paths resolve correctly.
        # pytest itself runs inside the container at /app, so the host CWD
        # does not affect test discovery.
        #
        # Build the pytest argv as a real array. Declining into a flattened
        # string would word-split paths/args containing spaces, parentheses
        # or shell metacharacters (e.g. `tests/Some Dir/test_x.py`).
        local _pytest_args=()
        if $USE_COVERAGE; then
            _pytest_args+=(--cov=app --cov-report=term --cov-report=html)
        fi
        _pytest_args+=("${EXTRA_ARGS[@]}")

        # To avoid Postgres connection exhaustion from the live dev server
        # (uvicorn workers + Celery) while tests run, stop the backend services
        # first, run tests in a fresh one-off container, then restart them.
        local _backend_was_running=false

        if is_backend_container_running; then
            _backend_was_running=true
            info "Stopping backend services for isolated test run..."
            $COMPOSE "${COMPOSE_ARGS[@]}" stop backend celery-worker celery-beat > /dev/null 2>&1 || true
        fi

        # Run tests in the dedicated backend-test container. Dev/test
        # dependencies are baked into the image (Dockerfile target=test),
        # so no runtime pip install is required.
        #
        # DATABASE_URL is intentionally cleared so the backend derives the URL
        # from the component env vars. An old DATABASE_URL in .env.development
        # would otherwise take precedence and route tests to the wrong database.
        #
        # Args are forwarded through positional `$@` of an inline `sh -c`
        # invocation so quoting/spaces survive intact (no `eval` of the
        # flattened argv string).
        #
        # --no-deps is required: when the dev stack is up, its postgres/redis
        # containers are pod members, and `compose run` fails trying to start
        # duplicate dependency containers ("container has joined pod ... and
        # dependency container ... is not a member of the pod"). Instead we
        # ensure the dependency containers are up ourselves and let the test
        # container resolve postgres/redis over the shared network.
        local _started_deps=false
        if ! { $CONTAINER_ENGINE ps --format '{{.Names}}' | grep -qx 'nukelab-postgres'; } \
            || ! { $CONTAINER_ENGINE ps --format '{{.Names}}' | grep -qx 'nukelab-redis'; }; then
            info "Starting postgres/redis for the test run..."
            $COMPOSE "${COMPOSE_ARGS[@]}" up -d postgres redis > /dev/null 2>&1
            _started_deps=true
            # Wait for Postgres to accept connections before running pytest.
            local _pg_ready=false
            for _ in $(seq 1 30); do
                if $CONTAINER_ENGINE exec nukelab-postgres \
                    pg_isready -U "${DATABASE_USER:-nukelab}" > /dev/null 2>&1; then
                    _pg_ready=true
                    break
                fi
                sleep 1
            done
            if ! $_pg_ready; then
                warn "Postgres did not become ready in time; tests may fail to connect."
            fi
        fi

        local _test_exit=0
        $COMPOSE --profile test "${COMPOSE_ARGS[@]}" run --rm --no-deps \
            -v "${DIR}/backend:/app:Z" \
            -v "${DIR}/resources:/app/resources:ro" \
            -e "DATABASE_USER=${DATABASE_USER:-nukelab}" \
            -e "DATABASE_PASSWORD=${DATABASE_PASSWORD:-nukelab123}" \
            -e "DATABASE_NAME=${DATABASE_NAME:-nukelab}_test" \
            -e "DATABASE_HOST=${DATABASE_HOST:-postgres}" \
            -e "DATABASE_PORT=${DATABASE_PORT:-5432}" \
            -e "DATABASE_URL=" \
            -e "REDIS_URL=redis://redis:6379/1" \
            -e "RATE_LIMIT_ENABLED=false" \
            -e "OTEL_TRACES_ENABLED=false" \
            -e "SENTRY_DSN=" \
            -e "PROMETHEUS_SCRAPE_TOKEN=" \
            -e "PROMETHEUS_ENABLED=false" \
            -e "REQUEST_METRICS_STORE=prometheus" \
            -e "PGBOUNCER_ENABLED=false" \
            -e "TESTING=true" \
            backend-test sh -c 'python -m pytest "$@"' _ "${_pytest_args[@]}" || _test_exit=$?

        # Stop the dependency containers again only if we started them.
        if $_started_deps; then
            $COMPOSE "${COMPOSE_ARGS[@]}" stop postgres redis > /dev/null 2>&1 || true
        fi

        # Restart backend services if they were running before. This must run
        # even when tests failed, otherwise the stack is left down.
        if $_backend_was_running; then
            info "Restarting backend services..."
            $COMPOSE "${COMPOSE_ARGS[@]}" up -d backend celery-worker celery-beat > /dev/null 2>&1 \
                || warn "Failed to restart backend services — the stack may be left down.\nRun './nukelabctl start backend' to bring it back up."
        fi

        if [ "$_test_exit" -ne 0 ]; then
            warn "Backend tests failed (exit $_test_exit)"
            _failed_suites+=("backend")
        fi
    fi

    if [ ${#_failed_suites[@]} -gt 0 ]; then
        err "Test suites failed: ${_failed_suites[*]}"
        exit 1
    fi
}

help_test() {
    cat <<- EOF
${BOLD}Usage:${RESET} ./nukelabctl test [target]

Run tests. Exits non-zero if any selected suite fails (all selected suites
still run to completion).

${BOLD}Targets:${RESET} frontend | backend | all

${BOLD}Options:${RESET}
  --coverage    Run backend tests with coverage report

${BOLD}Examples:${RESET}
  ./nukelabctl test
  ./nukelabctl test backend
  ./nukelabctl test backend --coverage
  ./nukelabctl test backend tests/services/test_volume_service.py
  ./nukelabctl test backend tests/services/ tests/tasks/test_tasks.py -x -v
  ./nukelabctl test backend -k "quota and not integration"

Any EXTRA_ARGS after the target are passed through to pytest (single file,
directory, node id, or pytest flags like -k, -x, --lf, --ff).
EOF
}
