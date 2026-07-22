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

    mkdir -p "$backup_dir"
    step "Creating backup..."

    # pg_dump's stdout IS the backup, so redirect it to the file directly.
    # Routing through _run_quiet_unless_verbose would send stdout to /dev/null
    # unless --verbose is set, producing an empty backup. stderr stays visible
    # so pg_dump errors surface.
    local _dump_exit=0
    $COMPOSE "${COMPOSE_ARGS[@]}" exec -T postgres pg_dump -U "${DATABASE_USER:-nukelab}" "${DATABASE_NAME:-nukelab}" > "$backup_file" || _dump_exit=$?

    if [ "$_dump_exit" -ne 0 ]; then
        rm -f "$backup_file"
        die "Backup failed: pg_dump exited with status $_dump_exit (partial file removed)"
    fi
    if [ ! -s "$backup_file" ]; then
        rm -f "$backup_file"
        die "Backup failed: pg_dump produced an empty backup (file removed)"
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
