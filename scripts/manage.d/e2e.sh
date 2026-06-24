cmd_e2e() {
    step "Running E2E tests..."
    cd "$DIR/frontend"
    [ -d "node_modules" ] || die "Run: ./manage.sh install frontend"
    if ! command -v npx > /dev/null 2>&1; then
        die "npx not found"
    fi
    if ! npx playwright test --version > /dev/null 2>&1; then
        warn "Playwright not installed. Run: ./manage.sh install frontend"
    fi
    if ! curl -sf "${APP_URL:-http://localhost:8080}/api/health" > /dev/null 2>&1; then
        warn "Backend does not appear to be running. Start it first:\n  ./manage.sh start --dev"
        die "Backend health check failed"
    fi
    ok "Backend detected"
    npx playwright test
}

help_e2e() {
    cat <<-EOF
${BOLD}Usage:${RESET} ./manage.sh e2e

Run Playwright end-to-end tests. The backend must be running.

${BOLD}Examples:${RESET}
  ./manage.sh e2e
EOF
}

