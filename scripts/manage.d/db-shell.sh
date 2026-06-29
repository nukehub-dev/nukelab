#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

cmd_db_shell() {
    if ! _container_running nukelab-postgres; then
        die "Postgres container is not running. Start the backend first:\n  ./nukelabctl start backend"
    fi
    step "Opening database shell..."
    $COMPOSE "${COMPOSE_ARGS[@]}" exec postgres psql -U "${DATABASE_USER:-nukelab}" -d "${DATABASE_NAME:-nukelab}"
}

help_db_shell() {
    cat <<- EOF
${BOLD}Usage:${RESET} ./nukelabctl db-shell

Open a psql shell inside the postgres container.

${BOLD}Examples:${RESET}
  ./nukelabctl db-shell
EOF
}
