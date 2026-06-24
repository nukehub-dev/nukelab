cmd_loadtest() {
    local profile="${TARGET:-baseline}"
    step "Running load test: ${BOLD}$profile${RESET}"
    if [ ! -f "$DIR/scripts/run-load-tests.sh" ]; then
        die "Load-test script not found: $DIR/scripts/run-load-tests.sh"
    fi
    bash "$DIR/scripts/run-load-tests.sh" "$profile"
}
