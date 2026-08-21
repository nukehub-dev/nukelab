#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

cmd_backup() {
    local backup_dir="$DIR/backups"
    local timestamp=$(date +%Y%m%d_%H%M%S)
    local backup_file="$backup_dir/nukelab_backup_$timestamp.sql"

    if ! _container_running nukelab-postgres; then
        die "Postgres container is not running. Start the backend first:\n  ./nukelabctl start backend"
    fi

    step "Creating backup..."

    if ! _pg_dump_backup "$backup_file"; then
        die "Backup failed: pg_dump exited with a non-zero status or produced an empty backup (partial file removed)"
    fi

    ok "Backup created: ${CYAN}$backup_file${RESET}"
}

help_backup() {
    cat <<- EOF
${BOLD}Usage:${RESET} ./nukelabctl backup

Create a database backup in backups/.

${BOLD}Examples:${RESET}
  ./nukelabctl backup
EOF
}
