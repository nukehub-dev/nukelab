help_selftest() {
    cat <<-EOF
${BOLD}Usage:${RESET} ./manage.sh selftest

Run a quick sanity check on manage.sh argument parsing and help output.
This does not start or stop any containers.

${BOLD}Examples:${RESET}
  ./manage.sh selftest
EOF
}

# Run a subcommand and print a pass/fail line.
# Usage: _t <name> <command>
_t() {
    local name="$1"
    shift
    if "$@" >/dev/null 2>&1; then
        ok "$name"
    else
        err "$name"
        return 1
    fi
}

cmd_selftest() {
    step "Running manage.sh self-test"

    local failures=0

    # Help output
    _t "top-level help" bash -c './manage.sh help | grep -q "NukeLab v2.0"' || ((failures++))
    _t "command help: start" bash -c './manage.sh start --help | grep -q "Start the NukeLab stack"' || ((failures++))
    _t "command help: logs" bash -c './manage.sh logs --help | grep -q "Stream container logs"' || ((failures++))
    _t "command help: stop" bash -c './manage.sh stop --help | grep -q "Stop running containers"' || ((failures++))
    _t "command help: status" bash -c './manage.sh status --help | grep -q "Show the status"' || ((failures++))

    # Global flags do not break help
    _t "--verbose help" bash -c './manage.sh --verbose help >/dev/null 2>&1' || ((failures++))
    _t "--quiet help" bash -c './manage.sh --quiet help >/dev/null 2>&1' || ((failures++))

    # Quiet mode suppresses logger output
    _t "--quiet suppresses info" bash -c '! ./manage.sh --quiet status --running 2>&1 | grep -q "Loading"' || ((failures++))

    # Argument parsing: value-taking options get their value, not treated as target
    _t "logs --tail parses" bash -c './manage.sh logs --tail 5 --no-follow backend 2>&1 | grep -vq "Option --tail requires a value"' || ((failures++))
    _t "stop --timeout parses" bash -c './manage.sh stop --timeout 5 2>&1 | grep -vq "Unexpected argument"' || ((failures++))

    # Invalid option values are rejected
    if ./manage.sh logs --tail abc --no-follow backend >/dev/null 2>&1; then
        err "invalid --tail value not rejected"
        ((failures++))
    else
        ok "invalid --tail value rejected"
    fi

    if ./manage.sh stop --timeout abc >/dev/null 2>&1; then
        err "invalid --timeout value not rejected"
        ((failures++))
    else
        ok "invalid --timeout value rejected"
    fi

    # Unknown options are rejected
    if ./manage.sh logs --bogus >/dev/null 2>&1; then
        err "unknown option not rejected"
        ((failures++))
    else
        ok "unknown option rejected"
    fi

    echo ""
    if [ "$failures" -eq 0 ]; then
        ok "All self-tests passed"
    else
        die "$failures self-test(s) failed"
    fi
}
