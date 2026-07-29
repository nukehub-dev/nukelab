#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

cmd_install() {
    if [ "$TARGET" = "frontend" ] || [ "$TARGET" = "all" ]; then
        step "Installing frontend dependencies..."
        command -v npm > /dev/null 2>&1 || die "npm not found"
        cd "$DIR/frontend"
        npm install
        ok "Frontend dependencies installed"
    fi

    if [ "$TARGET" = "backend" ] || [ "$TARGET" = "all" ]; then
        info "Backend dependencies are managed via Docker (requirements.txt). No local installation needed."
    fi
}

# install takes no flags; validate only that the target is a real one so a
# typo (e.g. `install fronend`) fails loudly instead of silently doing nothing.
parse_install_args() {
    case "$TARGET" in
        backend | frontend | all) ;;
        *)
            die "Unknown target for install: $TARGET\nRun './nukelabctl install --help' for usage."
            ;;
    esac
}

help_install() {
    cat <<- EOF
${BOLD}Usage:${RESET} ./nukelabctl install [target]

Install local dependencies.

${BOLD}Targets:${RESET} frontend | backend | all

${BOLD}Examples:${RESET}
  ./nukelabctl install frontend
  ./nukelabctl install
EOF
}
