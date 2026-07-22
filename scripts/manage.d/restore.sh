#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Default values for restore options.
RESTORE_YES=false

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

    local db_user="${DATABASE_USER:-nukelab}"
    local db_name="${DATABASE_NAME:-nukelab}"

    # Restoring drops the current database, so require explicit confirmation.
    # The only non-interactive bypass is --yes; never read from a non-TTY.
    if ! $RESTORE_YES; then
        step "${RED}${BOLD}WARNING:${RESET} This drops and recreates database ${BOLD}$db_name${RESET}!"
        if [ ! -t 0 ]; then
            die "Restore requires confirmation, but stdin is not a terminal.\nPass --yes to confirm non-interactively."
        fi
        read -rp "Type 'yes' to confirm: " confirm || die "Confirmation required (no input); aborting."
        [[ "$confirm" = "yes" ]] || {
            info "Aborted."
            exit 0
        }
    fi

    step "Restoring from ${BOLD}$backup_file${RESET}..."

    # Drop/create must run against the maintenance database: you cannot drop
    # the database you are connected to. WITH (FORCE) kicks out the backend's
    # live connections first (PostgreSQL 13+).
    log "Dropping database if exists..."
    _run_quiet_unless_verbose $COMPOSE "${COMPOSE_ARGS[@]}" exec -T postgres psql -U "$db_user" -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS $db_name WITH (FORCE);"

    log "Creating database..."
    _run_quiet_unless_verbose $COMPOSE "${COMPOSE_ARGS[@]}" exec -T postgres psql -U "$db_user" -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE $db_name;"

    log "Restoring data..."
    _run_quiet_unless_verbose $COMPOSE "${COMPOSE_ARGS[@]}" exec -T postgres psql -U "$db_user" -v ON_ERROR_STOP=1 -d "$db_name" < "$backup_file"

    log "Stamping alembic version..."
    _run_quiet_unless_verbose $COMPOSE "${COMPOSE_ARGS[@]}" exec -T backend python -m alembic stamp head

    ok "Restore complete"
}

parse_restore_args() {
    while [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; do
        case "${EXTRA_ARGS[0]}" in
            --yes | -y)
                RESTORE_YES=true
                EXTRA_ARGS=("${EXTRA_ARGS[@]:1}")
                ;;
            --help | -h)
                help_restore
                exit 0
                ;;
            --*)
                die "Unknown option for restore: ${EXTRA_ARGS[0]}"
                ;;
            *)
                if [[ -z "${TARGET:-}" || "$TARGET" == "all" ]]; then
                    TARGET="${EXTRA_ARGS[0]}"
                    EXTRA_ARGS=("${EXTRA_ARGS[@]:1}")
                else
                    die "Unexpected argument: ${EXTRA_ARGS[0]}"
                fi
                ;;
        esac
    done
}

help_restore() {
    cat <<- EOF
${BOLD}Usage:${RESET} ./nukelabctl restore <backup-file> [options]

Restore the database from a backup file. This drops and recreates the
database, so it requires typing 'yes' to confirm unless --yes is given.

${BOLD}Options:${RESET}
  --yes, -y    Skip the confirmation prompt (for scripts)

${BOLD}Examples:${RESET}
  ./nukelabctl restore backups/nukelab_backup_20250607_120000.sql
  ./nukelabctl restore --yes backups/nukelab_backup_20250607_120000.sql
EOF
}
