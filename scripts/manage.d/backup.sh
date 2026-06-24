cmd_backup() {
    local backup_dir="$DIR/backups"
    local timestamp=$(date +%Y%m%d_%H%M%S)
    local backup_file="$backup_dir/nukelab_backup_$timestamp.sql"

    if ! _container_running nukelab-postgres; then
        die "Postgres container is not running. Start the backend first:\n  ./nukelabctl start backend"
    fi

    mkdir -p "$backup_dir"
    step "Creating backup..."

    _run_quiet_unless_verbose $COMPOSE "${COMPOSE_ARGS[@]}" exec -T postgres pg_dump -U "${DATABASE_USER:-nukelab}" "${DATABASE_NAME:-nukelab}" > "$backup_file"

    ok "Backup created: ${CYAN}$backup_file${RESET}"
}

help_backup() {
    cat <<-EOF
${BOLD}Usage:${RESET} ./nukelabctl backup

Create a database backup in backups/.

${BOLD}Examples:${RESET}
  ./nukelabctl backup
EOF
}

