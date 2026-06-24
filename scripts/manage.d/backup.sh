cmd_backup() {
    local backup_dir="$DIR/backups"
    local timestamp=$(date +%Y%m%d_%H%M%S)
    local backup_file="$backup_dir/nukelab_backup_$timestamp.sql"

    mkdir -p "$backup_dir"
    step "Creating backup..."

    $COMPOSE "${COMPOSE_ARGS[@]}" exec -T postgres pg_dump -U "${DATABASE_USER:-nukelab}" "${DATABASE_NAME:-nukelab}" > "$backup_file"

    ok "Backup created: ${CYAN}$backup_file${RESET}"
}
