#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

cmd_e2e() {
    step "Running E2E tests..."
    cd "$DIR/frontend"
    [ -d "node_modules" ] || die "Run: ./nukelabctl install frontend"
    if ! command -v npx > /dev/null 2>&1; then
        die "npx not found"
    fi
    if ! npx playwright test --version > /dev/null 2>&1; then
        warn "Playwright not installed; installing now (one-time)..."
        npx playwright install --with-deps || die "Failed to install Playwright. Run: ./nukelabctl install frontend"
    fi
    if ! curl -sf "${APP_URL:-http://localhost:8080}/api/health" > /dev/null 2>&1; then
        warn "Backend does not appear to be running. Start it first:\n  ./nukelabctl dev"
        die "Backend health check failed"
    fi
    ok "Backend detected"
    # Forward EXTRA_ARGS so users can scope runs, e.g.
    #   ./nukelabctl e2e --grep login --workers 1
    if [ ${#EXTRA_ARGS[@]} -gt 0 ]; then
        npx playwright test "${EXTRA_ARGS[@]}"
    else
        npx playwright test
    fi
}

help_e2e() {
    cat <<- EOF
${BOLD}Usage:${RESET} ./nukelabctl e2e [playwright-args...]

Run Playwright end-to-end tests. The backend must be running. Any arguments
after the command — including positional spec files — are forwarded to
\`npx playwright test\`, so you can scope runs by file, grep, project, etc.

${BOLD}Examples:${RESET}
  ./nukelabctl e2e
  ./nukelabctl e2e --grep "login"
  ./nukelabctl e2e tests/login.spec.ts --workers 1
EOF
}
