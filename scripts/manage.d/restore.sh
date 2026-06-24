cmd_restore() {
    local backup_file="${TARGET:-}"

    if [ -z "$backup_file" ] || [ "$backup_file" = "all" ]; then
        die "Usage: ./manage.sh restore <backup-file>\nExample: ./manage.sh restore backups/nukelab_backup_20250607_120000.sql"
    fi

    if [ ! -f "$backup_file" ]; then
        die "Backup file not found: $backup_file"
    fi

    step "Restoring from ${BOLD}$backup_file${RESET}..."

    local db_user="${DATABASE_USER:-nukelab}"
    local db_name="${DATABASE_NAME:-nukelab}"

    log "Dropping database if exists..."
    $COMPOSE "${COMPOSE_ARGS[@]}" exec postgres psql -U "$db_user" -c "DROP DATABASE IF EXISTS $db_name;"

    log "Creating database..."
    $COMPOSE "${COMPOSE_ARGS[@]}" exec postgres psql -U "$db_user" -c "CREATE DATABASE $db_name;"

    log "Restoring data..."
    $COMPOSE "${COMPOSE_ARGS[@]}" exec -T postgres psql -U "$db_user" -d "$db_name" < "$backup_file"

    log "Stamping alembic version..."
    $COMPOSE "${COMPOSE_ARGS[@]}" exec backend python -m alembic stamp 281a4c5d5529

    ok "Restore complete"
}

help_restore() {
    cat <<-EOF
${BOLD}Usage:${RESET} ./manage.sh restore <backup-file>

Restore the database from a backup file.

${BOLD}Examples:${RESET}
  ./manage.sh restore backups/nukelab_backup_20250607_120000.sql
EOF
}

