#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

cmd_restore() {
    local backup_file="${TARGET:-}"

    if [ -z "$backup_file" ] || [ "$backup_file" = "all" ]; then
        die "Usage: ./nukelabctl restore <backup-file>\nExample: ./nukelabctl restore backups/nukelab_backup_20250607_120000.sql"
    fi

    if [ ! -f "$backup_file" ]; then
        die "Backup file not found: $backup_file"
    fi

    if ! _container_running nukelab-postgres; then
        die "Postgres container is not running. Start the backend first:\n  ./nukelabctl start backend"
    fi

    step "Restoring from ${BOLD}$backup_file${RESET}..."

    local db_user="${DATABASE_USER:-nukelab}"
    local db_name="${DATABASE_NAME:-nukelab}"

    log "Dropping database if exists..."
    _run_quiet_unless_verbose $COMPOSE "${COMPOSE_ARGS[@]}" exec postgres psql -U "$db_user" -c "DROP DATABASE IF EXISTS $db_name;"

    log "Creating database..."
    _run_quiet_unless_verbose $COMPOSE "${COMPOSE_ARGS[@]}" exec postgres psql -U "$db_user" -c "CREATE DATABASE $db_name;"

    log "Restoring data..."
    _run_quiet_unless_verbose $COMPOSE "${COMPOSE_ARGS[@]}" exec -T postgres psql -U "$db_user" -d "$db_name" < "$backup_file"

    log "Stamping alembic version..."
    _run_quiet_unless_verbose $COMPOSE "${COMPOSE_ARGS[@]}" exec backend python -m alembic stamp 8298b4bb8ada

    ok "Restore complete"
}

help_restore() {
    cat <<- EOF
${BOLD}Usage:${RESET} ./nukelabctl restore <backup-file>

Restore the database from a backup file.

${BOLD}Examples:${RESET}
  ./nukelabctl restore backups/nukelab_backup_20250607_120000.sql
EOF
}
