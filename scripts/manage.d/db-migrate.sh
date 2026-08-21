#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Default values for db-migrate options.
DB_MIGRATE_NO_BACKUP=false

cmd_db_migrate() {
    step "Running database migrations..."

    if ! is_backend_container_running; then
        die "Backend not running. Start it first:\n  ./nukelabctl start backend"
    fi

    local snapshot_file=""
    local backup_created=false
    local rev="none"
    local ts
    ts=$(date +%Y%m%d_%H%M%S)

    if ! $DB_MIGRATE_NO_BACKUP; then
        # Query current Alembic revision before the upgrade. Use psql directly
        # against postgres so this works even if the backend env/alembic CLI is
        # in an unexpected state.
        rev=$(_current_alembic_revision)
        snapshot_file="$DIR/backups/pre-migrate-${NUKELAB_VERSION}-${rev}-${ts}.dump"

        step "Creating pre-migration snapshot ${snapshot_file}..."
        if ! _pg_dump_backup "$snapshot_file"; then
            die "Pre-migration backup failed; migration aborted to avoid an unprotected upgrade"
        fi
        backup_created=true
        ok "Pre-migration snapshot created: ${CYAN}$snapshot_file${RESET}"
    fi

    # Force a direct Postgres URL even if DATABASE_URL points to PgBouncer;
    # DDL must not go through the connection pooler.
    local direct_url
    direct_url=$(_direct_database_url)
    if [[ "${DATABASE_HOST:-postgres}" == "pgbouncer" ]] || [[ "${DATABASE_PORT:-5432}" == "6432" ]]; then
        info "Routing migration through direct Postgres connection"
    fi

    local _migrate_exit=0
    _run_quiet_unless_verbose $COMPOSE "${COMPOSE_ARGS[@]}" exec -e "DATABASE_URL=$direct_url" backend alembic upgrade head || _migrate_exit=$?

    if [ "$_migrate_exit" -ne 0 ]; then
        if $backup_created; then
            err "Migration failed. To restore the pre-migration snapshot, run:"
            err "  ./nukelabctl restore ${snapshot_file}"
        fi
        die "Migration failed: alembic upgrade head exited with status $_migrate_exit"
    fi

    ok "Migrations applied"
}

# Return the current Alembic revision stored in the database, or "none" if the
# alembic_version table does not exist yet (fresh/unmanaged database).
_current_alembic_revision() {
    local rev=""
    local _exit=0
    rev=$($COMPOSE "${COMPOSE_ARGS[@]}" exec -T postgres \
        psql -U "${DATABASE_USER:-nukelab}" -d "${DATABASE_NAME:-nukelab}" \
        -v ON_ERROR_STOP=1 -t -A \
        -c "SELECT version_num FROM alembic_version LIMIT 1" 2> /dev/null | tr -d '[:space:]') || _exit=$?
    if [ "$_exit" -ne 0 ] || [ -z "$rev" ]; then
        echo "none"
    else
        echo "$rev"
    fi
}

parse_db_migrate_args() {
    while [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; do
        case "${EXTRA_ARGS[0]}" in
            --no-backup)
                DB_MIGRATE_NO_BACKUP=true
                EXTRA_ARGS=("${EXTRA_ARGS[@]:1}")
                ;;
            --help | -h)
                help_db_migrate
                exit 0
                ;;
            --*)
                die "Unknown option for db-migrate: ${EXTRA_ARGS[0]}"
                ;;
            *)
                die "Unexpected argument for db-migrate: ${EXTRA_ARGS[0]}"
                ;;
        esac
    done
}

help_db_migrate() {
    cat <<- EOF
${BOLD}Usage:${RESET} ./nukelabctl db-migrate [options]

Run Alembic database migrations inside the backend container.

A pg_dump snapshot is taken automatically before the upgrade. The filename
includes the platform version, the current Alembic revision, and a timestamp:
backups/pre-migrate-<version>-<revision>-<timestamp>.dump

${BOLD}Options:${RESET}
  --no-backup    Skip the automatic pre-migration snapshot

${BOLD}Examples:${RESET}
  ./nukelabctl db-migrate
  ./nukelabctl db-migrate --no-backup
EOF
}
