cmd_loadtest() {
    local profile="${TARGET:-baseline}"
    step "Running load test: ${BOLD}$profile${RESET}"
    if [ ! -f "$DIR/scripts/run-load-tests.sh" ]; then
        die "Load-test script not found: $DIR/scripts/run-load-tests.sh"
    fi
    bash "$DIR/scripts/run-load-tests.sh" "$profile"
}

help_loadtest() {
    cat <<-EOF
${BOLD}Usage:${RESET} ./nukelabctl loadtest [profile]

Run Locust/k6 load tests. The backend must be running.

${BOLD}Profiles:${RESET}
  smoke, baseline, stress, spike, endurance, connection
  k6-smoke, k6-baseline, k6-stress, k6-spike, k6-endurance
  all            Run all Locust and k6 profiles sequentially

${BOLD}Examples:${RESET}
  ./nukelabctl loadtest           # Default: baseline
  ./nukelabctl loadtest smoke
  ./nukelabctl loadtest baseline
  ./nukelabctl loadtest stress
  ./nukelabctl loadtest all       # Run every profile
EOF
}

