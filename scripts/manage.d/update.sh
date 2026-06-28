#!/bin/bash
# Default: rebuild without the layer cache to always pick up changes from
# base images. --cache lets users reuse layers when iterating.
UPDATE_BUILD_ARGS=(--no-cache)

parse_update_args() {
    while [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; do
        case "${EXTRA_ARGS[0]}" in
            --cache)
                UPDATE_BUILD_ARGS=()
                EXTRA_ARGS=("${EXTRA_ARGS[@]:1}")
                ;;
            --help | -h)
                help_update
                exit 0
                ;;
            --*)
                die "Unknown option for update: ${EXTRA_ARGS[0]}"
                ;;
            *)
                die "Unexpected argument: ${EXTRA_ARGS[0]}"
                ;;
        esac
    done
}

cmd_update() {
    step "Updating NukeLab..."

    log "Pulling latest images..."
    _run_quiet_unless_verbose $COMPOSE "${COMPOSE_ARGS[@]}" pull

    log "Rebuilding containers..."
    _run_quiet_unless_verbose $COMPOSE "${COMPOSE_ARGS[@]}" build "${UPDATE_BUILD_ARGS[@]}"

    ok "Update complete! Run './nukelabctl restart' to apply changes."
}

help_update() {
    cat <<- EOF
${BOLD}Usage:${RESET} ./nukelabctl update [--cache]

Pull latest base images and rebuild all containers.

${BOLD}Options:${RESET}
  --cache    Reuse Docker/Podman layer cache instead of forcing --no-cache.
             Faster on repeat runs; may miss changes from updated base images.

${BOLD}Examples:${RESET}
  ./nukelabctl update
  ./nukelabctl update --cache
EOF
}
