#!/bin/bash
cmd_exec() {
    local service="${TARGET:-backend}"
    if [[ "$service" = "all" ]]; then
        service="backend"
    fi

    if [ ${#EXTRA_ARGS[@]} -eq 0 ]; then
        die "Usage: ./nukelabctl exec <service> <command>\nExample: ./nukelabctl exec backend ls -la"
    fi

    $COMPOSE "${COMPOSE_ARGS[@]}" exec "$service" "${EXTRA_ARGS[@]}"
}

help_exec() {
    cat <<- EOF
${BOLD}Usage:${RESET} ./nukelabctl exec <service> <command> [args...]

Execute a command inside a running container.

${BOLD}Examples:${RESET}
  ./nukelabctl exec backend ls -la
  ./nukelabctl exec backend python -v
EOF
}
