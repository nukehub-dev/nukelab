#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

cmd_rotate_user_auth_key() {
    local service="${TARGET:-backend}"
    if [[ "$service" = "all" ]]; then
        service="backend"
    fi

    if ! is_backend_container_running; then
        die "Backend container is not running. Start the stack first:\n  ./nukelabctl start"
    fi

    step "Rotating user-auth Ed25519 key in ${service}..."
    $COMPOSE "${COMPOSE_ARGS[@]}" exec "$service" python scripts/rotate_user_auth_key.py
}

help_rotate_user_auth_key() {
    cat <<- EOF
${BOLD}Usage:${RESET} ./nukelabctl rotate-user-auth-key [service]

Rotate the active Ed25519 user-auth signing key inside the backend container.
The old public key is kept as a retired verification key for the configured
grace period so in-flight access tokens continue to validate.

${BOLD}Examples:${RESET}
  ./nukelabctl rotate-user-auth-key
EOF
}
