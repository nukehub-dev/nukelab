#!/bin/bash
cmd_cleanup_user_auth_keys() {
    local service="${TARGET:-backend}"
    if [[ "$service" = "all" ]]; then
        service="backend"
    fi

    if ! is_backend_container_running; then
        die "Backend container is not running. Start the stack first:\n  ./nukelabctl start"
    fi

    step "Cleaning up expired retired user-auth public keys in ${service}..."
    $COMPOSE "${COMPOSE_ARGS[@]}" exec "$service" python scripts/rotate_user_auth_key.py --cleanup
}

help_cleanup_user_auth_keys() {
    cat <<- EOF
${BOLD}Usage:${RESET} ./nukelabctl cleanup-user-auth-keys [service]

Remove retired user-auth public keys whose grace period has expired.

${BOLD}Examples:${RESET}
  ./nukelabctl cleanup-user-auth-keys
EOF
}
