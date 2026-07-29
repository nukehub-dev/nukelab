#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

help_version() {
    cat <<- EOF
${BOLD}Usage:${RESET} ./nukelabctl version

Show the NukeLab version and detected container engine versions.

${BOLD}Examples:${RESET}
  ./nukelabctl version
  ./nukelabctl --version
EOF
}

# _nukelab_version lives in scripts/lib.sh so it is available to print_help
# (which runs before command modules are sourced) as well as this command.

cmd_version() {
    echo "${BOLD}NukeLab $(_nukelab_version)${RESET}"
    echo ""
    echo "Container engine: ${CONTAINER_ENGINE:-not detected}"
    if command -v "${CONTAINER_ENGINE:-podman}" > /dev/null 2>&1; then
        echo -n "  version: "
        "${CONTAINER_ENGINE:-podman}" --version 2> /dev/null | head -n 1
    fi
    echo "Compose command: ${COMPOSE:-not detected}"
    if [ -n "${COMPOSE:-}" ]; then
        echo -n "  version: "
        $COMPOSE version 2> /dev/null | head -n 1 || true
    fi
    echo "Project directory: $DIR"
}
