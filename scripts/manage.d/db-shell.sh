cmd_db_shell() {
    step "Opening database shell..."
    $COMPOSE "${COMPOSE_ARGS[@]}" exec postgres psql -U "${DATABASE_USER:-nukelab}" -d "${DATABASE_NAME:-nukelab}"
}

help_db_shell() {
    cat <<-EOF
${BOLD}Usage:${RESET} ./nukelabctl db-shell

Open a psql shell inside the postgres container.

${BOLD}Examples:${RESET}
  ./nukelabctl db-shell
EOF
}

