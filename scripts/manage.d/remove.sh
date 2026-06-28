cmd_remove() {
    step "Removing containers..."

    local _services
    _services=$(_backend_services)

    if [ "$TARGET" = "frontend" ] || [ "$TARGET" = "all" ]; then
        kill_frontend
        $COMPOSE "${COMPOSE_ARGS[@]}" rm -f frontend 2>/dev/null || true
        ok "Frontend container removed"
    fi

    if [ "$TARGET" = "backend" ] || [ "$TARGET" = "all" ]; then
        $COMPOSE "${COMPOSE_ARGS[@]}" rm -f $_services 2>/dev/null || true
        _stop_orphan_if_unmanaged "compose.pgbouncer.yml" nukelab-pgbouncer
        if ! _has_overlay "compose.pgbouncer.yml"; then
            local _cmd="podman"
            [ "$CONTAINER_ENGINE" = "docker" ] && _cmd="docker"
            $_cmd rm -f nukelab-pgbouncer > /dev/null 2>&1 || true
        fi
        ok "Backend containers removed"
    fi
}

# parse_remove_args validates flags so a typo (e.g. `rm --bogus`) is rejected
# instead of silently executing a destructive remove against the current
# target.
parse_remove_args() {
    while [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; do
        case "${EXTRA_ARGS[0]}" in
            --help|-h)
                help_remove
                exit 0
                ;;
            --*)
                die "Unknown option for remove: ${EXTRA_ARGS[0]}"
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

help_remove() {
    cat <<-EOF
${BOLD}Usage:${RESET} ./nukelabctl remove [target]

Remove containers while keeping volumes and data.

${BOLD}Targets:${RESET} backend | frontend | all

${BOLD}Examples:${RESET}
  ./nukelabctl remove
  ./nukelabctl remove backend
EOF
}

