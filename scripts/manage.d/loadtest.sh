#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

cmd_loadtest() {
    # Load tests always run against the prod stack because k6 needs multiple
    # uvicorn workers; the dev stack uses a single reload worker.
    USE_DEV_MODE=false

    local profile="${TARGET:-baseline}"
    step "Running load test: ${BOLD}$profile${RESET}"

    # Refuse to run if the dev stack is currently active.
    if [ -f "$DEV_STATE_FILE" ]; then
        local _dev_running=false
        local _saved_args=("${COMPOSE_ARGS[@]}")
        # shellcheck source=/dev/null
        source "$DEV_STATE_FILE"
        if [ ${#NUKELAB_COMPOSE_ARGS[@]} -gt 0 ]; then
            COMPOSE_ARGS=("${NUKELAB_COMPOSE_ARGS[@]}")
        else
            COMPOSE_ARGS=(-f "$COMPOSE_FILE" -f "$DEV_COMPOSE_FILE")
        fi
        if _is_stack_running; then
            _dev_running=true
        fi
        COMPOSE_ARGS=("${_saved_args[@]}")
        if $_dev_running; then
            die "Development stack is running.\n\nLoad tests require the production stack (multi-worker backend).\nStop dev first:\n  ./nukelabctl dev stop\n\nThen start prod:\n  ./nukelabctl start"
        fi
    fi

    if [ ! -f "$DIR/scripts/run-load-tests.sh" ]; then
        die "Load-test script not found: $DIR/scripts/run-load-tests.sh"
    fi
    bash "$DIR/scripts/run-load-tests.sh" "$profile"
}

help_loadtest() {
    cat <<- EOF
${BOLD}Usage:${RESET} ./nukelabctl loadtest [profile]

Run Locust/k6 load tests. The backend must be running.

${BOLD}Profiles:${RESET}
  smoke, baseline, stress, spike, endurance, connection
  k6-smoke, k6-baseline, k6-stress, k6-spike, k6-endurance
  all            Run all Locust and k6 profiles sequentially

${BOLD}Examples:${RESET}
  ./nukelabctl loadtest           # Default: baseline
  ./nukelabctl loadtest smoke
  ./nukelabctl loadtest baseline
  ./nukelabctl loadtest stress
  ./nukelabctl loadtest all       # Run every profile
EOF
}
