cmd_exec() {
    local service="${TARGET:-backend}"
    if [[ "$service" = "all" ]]; then
        service="backend"
    fi

    if [ ${#EXTRA_ARGS[@]} -eq 0 ]; then
        die "Usage: ./manage.sh exec <service> <command>\nExample: ./manage.sh exec backend ls -la"
    fi

    $COMPOSE "${COMPOSE_ARGS[@]}" exec "$service" "${EXTRA_ARGS[@]}"
}

help_exec() {
    cat <<-EOF
${BOLD}Usage:${RESET} ./manage.sh exec <service> <command> [args...]

Execute a command inside a running container.

${BOLD}Examples:${RESET}
  ./manage.sh exec backend ls -la
  ./manage.sh exec backend python -v
EOF
}

