#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

cmd_pull() {
    step "Pulling latest images..."
    $COMPOSE "${COMPOSE_ARGS[@]}" pull
    ok "Images pulled"
}

help_pull() {
    cat <<- EOF
${BOLD}Usage:${RESET} ./nukelabctl pull

Pull the latest base images used by compose services.

${BOLD}Examples:${RESET}
  ./nukelabctl pull
EOF
}
