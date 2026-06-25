# Default values for logs options.
LOGS_TAIL=""
LOGS_FOLLOW=true

help_logs() {
    cat <<-EOF
${BOLD}Usage:${RESET} ./nukelabctl logs [service] [options]

Stream container logs.

${BOLD}Options:${RESET}
  --tail N, -n N    Show last N lines per service
  --no-follow       Do not stream new log lines (just print and exit)
  --help, -h        Show this help

${BOLD}Examples:${RESET}
  ./nukelabctl logs backend          # Stream backend logs
  ./nukelabctl logs backend --tail 50
  ./nukelabctl logs --tail 100
  ./nukelabctl logs --no-follow
EOF
}

parse_logs_args() {
    local _tail_set=false
    while [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; do
        case "${EXTRA_ARGS[0]}" in
            --tail|-n)
                if [[ ${#EXTRA_ARGS[@]} -lt 2 ]]; then
                    die "Option ${EXTRA_ARGS[0]} requires a value"
                fi
                LOGS_TAIL="${EXTRA_ARGS[1]}"
                _tail_set=true
                EXTRA_ARGS=("${EXTRA_ARGS[@]:2}")
                ;;
            --no-follow)
                LOGS_FOLLOW=false
                EXTRA_ARGS=("${EXTRA_ARGS[@]:1}")
                ;;
            --help|-h)
                help_logs
                exit 0
                ;;
            --*)
                die "Unknown option for logs: ${EXTRA_ARGS[0]}"
                ;;
            *)
                # Positional arg treated as service name if no target was given.
                if [[ -z "${TARGET:-}" || "$TARGET" == "all" ]]; then
                    TARGET="${EXTRA_ARGS[0]}"
                    EXTRA_ARGS=("${EXTRA_ARGS[@]:1}")
                else
                    die "Unexpected argument: ${EXTRA_ARGS[0]}"
                fi
                ;;
        esac
    done

    if $_tail_set && ! [[ "$LOGS_TAIL" =~ ^[0-9]+$ ]]; then
        die "--tail requires a non-negative integer, got: $LOGS_TAIL"
    fi
}

cmd_logs() {
    local service="${TARGET:-}"

    # 'all' is the default target for most commands, but for logs it means
    # "all services", which compose handles when no service is specified.
    if [[ "$service" == "all" ]]; then
        service=""
    fi

    # In dev mode, frontend runs locally via Vite, not a container.
    if $USE_DEV_MODE; then
        if [[ "$service" == "frontend" ]]; then
            die "In dev mode the frontend runs locally via Vite, not a container.\nCheck the terminal where you ran './nukelabctl dev' for frontend output."
        fi
        if [[ -z "$service" ]]; then
            log "Dev mode: frontend runs locally via Vite (check terminal for output)"
            service="traefik postgres redis backend celery-worker celery-beat"
        fi
    elif [[ -z "$service" ]]; then
        # Limit "all" logs to backend services plus frontend only when it is
        # actually running, so we don't spam errors for an unstarted frontend.
        service=$(_backend_services)
        if _container_running nukelab-frontend; then
            service="$service frontend"
        fi
    fi

    local _log_args=()
    if [ -n "$LOGS_TAIL" ]; then
        _log_args+=(--tail "$LOGS_TAIL")
    fi
    if $LOGS_FOLLOW; then
        _log_args+=(-f)
    fi

    $COMPOSE "${COMPOSE_ARGS[@]}" logs "${_log_args[@]}" ${service:-}
}
