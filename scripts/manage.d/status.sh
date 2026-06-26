# Default values for status options.
STATUS_RUNNING_ONLY=false

help_status() {
    cat <<-EOF
${BOLD}Usage:${RESET} ./nukelabctl status [options]

Show the status of all containers managed by the stack.

${BOLD}Options:${RESET}
  --running     Show only currently running containers
  --help, -h    Show this help

${BOLD}Examples:${RESET}
  ./nukelabctl status
  ./nukelabctl status --running
EOF
}

parse_status_args() {
    while [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; do
        case "${EXTRA_ARGS[0]}" in
            --running)
                STATUS_RUNNING_ONLY=true
                EXTRA_ARGS=("${EXTRA_ARGS[@]:1}")
                ;;
            --help|-h)
                help_status
                exit 0
                ;;
            --*)
                die "Unknown option for status: ${EXTRA_ARGS[0]}"
                ;;
            *)
                die "Unexpected argument: ${EXTRA_ARGS[0]}"
                ;;
        esac
    done
}

cmd_status() {
    step "Container Status"

    # podman-compose does not support the --filter flag on `ps`, so use the
    # container engine directly. Dev and prod share the same project prefix and
    # are mutually exclusive, so filtering by name is sufficient.
    if $STATUS_RUNNING_ONLY; then
        $CONTAINER_ENGINE ps --filter "name=^nukelab-" --filter "status=running"
    else
        $CONTAINER_ENGINE ps --filter "name=^nukelab-"
    fi

    echo ""
    if is_frontend_running; then
        ok "Frontend dev: ${CYAN}http://localhost:5173${RESET} ${DIM}(PID: $(cat "$FRONTEND_PID_FILE"))${RESET}"
    else
        info "Frontend dev: ${DIM}not running${RESET}"
    fi
}
