#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Default: rebuild without the layer cache to always pick up changes from
# base images. --cache lets users reuse layers when iterating.
UPDATE_BUILD_ARGS=(--no-cache)
UPDATE_FORCE_BUILD=false

parse_update_args() {
    while [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; do
        case "${EXTRA_ARGS[0]}" in
            --cache)
                UPDATE_BUILD_ARGS=()
                EXTRA_ARGS=("${EXTRA_ARGS[@]:1}")
                ;;
            --build)
                UPDATE_FORCE_BUILD=true
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

    if [ "${NUKELAB_PULL_DEPLOY:-false}" = "true" ]; then
        step "Pull-based update: pulling pinned registry images..."
        _run_quiet_unless_verbose $COMPOSE "${COMPOSE_ARGS[@]}" pull backend frontend
        # Pinning the app images must not freeze the infra base images.
        # Intentional word-split of the space-separated service list.
        # shellcheck disable=SC2086
        _run_quiet_unless_verbose $COMPOSE "${COMPOSE_ARGS[@]}" pull $(_pullable_infra_services)
        if $UPDATE_FORCE_BUILD; then
            log "Force source rebuild requested (--build)..."
            _run_quiet_unless_verbose $COMPOSE "${COMPOSE_ARGS[@]}" build "${UPDATE_BUILD_ARGS[@]}"
        fi
    else
        # Source-build path: refresh base images for the pullable infra
        # services only. The app services carry ghcr.io image: references for
        # pull-based deploys; pulling them here would fail without registry
        # auth, so they are excluded via _pullable_infra_services.
        log "Pulling latest base images..."
        # Intentional word-split of the space-separated service list.
        # shellcheck disable=SC2086
        _run_quiet_unless_verbose $COMPOSE "${COMPOSE_ARGS[@]}" pull $(_pullable_infra_services)

        log "Rebuilding containers..."
        _run_quiet_unless_verbose $COMPOSE "${COMPOSE_ARGS[@]}" build "${UPDATE_BUILD_ARGS[@]}"
    fi

    ok "Update complete! Run './nukelabctl restart' to apply changes."
}

help_update() {
    cat <<- EOF
${BOLD}Usage:${RESET} ./nukelabctl update [--cache] [--build]

Pull latest base images and rebuild all containers.

In pull-based deploy mode (NUKELAB_VERSION or NUKELAB_IMAGE_TAG is pinned),
this pulls the pinned ghcr.io images and skips the source build. Use --build
in pull mode to force a source rebuild anyway.

${BOLD}Options:${RESET}
  --cache    Reuse Docker/Podman layer cache instead of forcing --no-cache.
             Faster on repeat runs; may miss changes from updated base images.
  --build    Force a source rebuild even in pull-based deploy mode.

${BOLD}Examples:${RESET}
  ./nukelabctl update
  ./nukelabctl update --cache
  ./nukelabctl update --build
EOF
}
