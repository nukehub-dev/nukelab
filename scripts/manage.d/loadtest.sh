cmd_loadtest() {
    local profile="${TARGET:-baseline}"
    if [ "$profile" = "all" ]; then
        profile="baseline"
    fi
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

${BOLD}Examples:${RESET}
  ./nukelabctl loadtest smoke
  ./nukelabctl loadtest baseline
  ./nukelabctl loadtest stress
EOF
}

