help_dev() {
    cat <<-EOF
${BOLD}Usage:${RESET} ./nukelabctl dev [subcommand] [args...]

Manage the development stack: backend containers with hot-reload plus a local
Vite dev server on http://localhost:5173.

${BOLD}Subcommands:${RESET}
  start    [target] [options]   Start the dev stack ${DIM}(default)${RESET}
  restart  [target]             Restart dev stack services
  stop     [target]             Stop dev stack services
  logs     [service] [options]  Stream dev stack logs
  status   [options]            Show dev stack status

${BOLD}Start Options:${RESET}
  --no-build      Skip building images before starting
  --no-wait       Do not wait for the backend health check

${BOLD}Examples:${RESET}
  ./nukelabctl dev
  ./nukelabctl dev start backend --no-build
  ./nukelabctl dev restart backend
  ./nukelabctl dev logs backend -f
  ./nukelabctl dev stop
EOF
}

parse_dev_args() {
    if [[ ${#EXTRA_ARGS[@]} -eq 0 ]]; then
        DEV_SUBCMD="start"
        return
    fi

    case "${EXTRA_ARGS[0]}" in
        start|restart|stop|logs|status)
            DEV_SUBCMD="${EXTRA_ARGS[0]}"
            EXTRA_ARGS=("${EXTRA_ARGS[@]:1}")
            ;;
        --help|-h)
            help_dev
            exit 0
            ;;
        *)
            # Options or targets without an explicit subcommand go to "start".
            DEV_SUBCMD="start"
            ;;
    esac
}

cmd_dev() {
    # Dev mode is already selected by the main dispatcher, including the dev
    # state file. parse_dev_args has already run via _dispatch_command, so
    # DEV_SUBCMD and EXTRA_ARGS are ready to use.
    USE_DEV_MODE=true

    case "$DEV_SUBCMD" in
        start)
            _acquire_lock
            # Dev and prod share container names; only one may run at a time.
            _require_other_stack_stopped
            setup_compose_args
            preflight_checks
            ;;
        restart|stop)
            _acquire_lock
            if ! restore_state; then
                setup_compose_args
            fi
            ;;
        logs|status)
            if ! restore_state; then
                setup_compose_args
            fi
            ;;
        *)
            die "Unknown dev subcommand: $DEV_SUBCMD\nRun './nukelabctl dev --help' for usage."
            ;;
    esac

    # Dispatch to the existing command module. It sees USE_DEV_MODE=true and
    # the dev compose overlay already configured.
    CMD="$DEV_SUBCMD"
    _dispatch_command "$DEV_SUBCMD"
}
