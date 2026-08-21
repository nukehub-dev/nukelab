#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

cmd_pull() {
    step "Pulling latest images..."
    if [ "${NUKELAB_PULL_DEPLOY:-false}" = "true" ]; then
        # Pull-based deploys: pull everything, including the pinned app images.
        $COMPOSE "${COMPOSE_ARGS[@]}" pull
    else
        # Source-build mode: app services are built locally, so pull only the
        # infra images — the ghcr.io app tags may be unavailable without
        # registry auth. Intentional word-split of the service list.
        # shellcheck disable=SC2086
        $COMPOSE "${COMPOSE_ARGS[@]}" pull $(_pullable_infra_services)
    fi
    ok "Images pulled"
}

help_pull() {
    cat <<- EOF
${BOLD}Usage:${RESET} ./nukelabctl pull

Pull the latest images used by compose services. In source-build mode
(default) only infra images (postgres, redis, traefik, enabled overlays) are
pulled — app images are built locally. In pull-based deploy mode
(NUKELAB_VERSION or NUKELAB_IMAGE_TAG pinned) the pinned ghcr.io app images
are pulled too.

${BOLD}Examples:${RESET}
  ./nukelabctl pull
EOF
}
