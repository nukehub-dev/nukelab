help_selftest() {
    cat <<-EOF
${BOLD}Usage:${RESET} ./nukelabctl selftest

Run a quick sanity check on nukelabctl argument parsing and help output.
This does not start or stop any containers.

${BOLD}Examples:${RESET}
  ./nukelabctl selftest
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

_increment_failures() {
    failures=$((failures + 1))
}

cmd_selftest() {
    step "Running nukelabctl self-test"

    local failures=0

    # Help output
    # Help output (the ASCII banner spells lowercase "nukelab"; match the
    # reliable "Usage:" header instead of a literal project name).
    _t "top-level help" bash -c './nukelabctl help | grep -q "Usage:"' || _increment_failures
    _t "command help: start" bash -c './nukelabctl start --help | grep -q "Start the NukeLab stack"' || _increment_failures
    _t "command help: dev" bash -c './nukelabctl dev --help | grep -q "development stack"' || _increment_failures
    _t "command help: logs" bash -c './nukelabctl logs --help | grep -q "Stream container logs"' || _increment_failures
    _t "command help: stop" bash -c './nukelabctl stop --help | grep -q "Stop running containers"' || _increment_failures
    _t "command help: status" bash -c './nukelabctl status --help | grep -q "Show the status"' || _increment_failures

    # Global flags do not break help
    _t "--verbose help" bash -c './nukelabctl --verbose help >/dev/null 2>&1' || _increment_failures
    _t "--quiet help" bash -c './nukelabctl --quiet help >/dev/null 2>&1' || _increment_failures
    _t "--no-alertmanager help" bash -c './nukelabctl --no-alertmanager help >/dev/null 2>&1' || _increment_failures

    # Quiet mode suppresses logger output
    _t "--quiet suppresses info" bash -c '! ./nukelabctl --quiet status --running 2>&1 | grep -q "Loading"' || _increment_failures

    # Argument parsing: value-taking options get their value, not treated as target
    _t "logs --tail parses" bash -c './nukelabctl logs --tail 5 --no-follow backend 2>&1 | grep -vq "Option --tail requires a value"' || _increment_failures
    _t "stop --timeout parses" bash -c './nukelabctl stop --timeout 5 2>&1 | grep -vq "Unexpected argument"' || _increment_failures

    # Invalid option values are rejected
    if ./nukelabctl logs --tail abc --no-follow backend >/dev/null 2>&1; then
        err "invalid --tail value not rejected"
        _increment_failures
    else
        ok "invalid --tail value rejected"
    fi

    if ./nukelabctl stop --timeout abc >/dev/null 2>&1; then
        err "invalid --timeout value not rejected"
        _increment_failures
    else
        ok "invalid --timeout value rejected"
    fi

    # Unknown options are rejected
    if ./nukelabctl logs --bogus >/dev/null 2>&1; then
        err "unknown option not rejected"
        _increment_failures
    else
        ok "unknown option rejected"
    fi

    # --dev global flag was removed; dev is now a meta-command
    if ./nukelabctl start --dev >/dev/null 2>&1; then
        err "removed --dev flag still accepted"
        _increment_failures
    else
        ok "removed --dev flag rejected"
    fi

    # dev meta-command subcommand parsing
    _t "dev defaults to start" bash -c './nukelabctl dev --help | grep -q "Start the dev stack"' || _increment_failures
    _t "dev start help" bash -c './nukelabctl dev start --help | grep -q "Start the NukeLab stack"' || _increment_failures
    _t "dev restart help" bash -c './nukelabctl dev restart --help | grep -q "Stop and then start"' || _increment_failures
    _t "dev logs --tail parses" bash -c './nukelabctl dev logs --tail 5 --no-follow backend 2>&1 | grep -vq "Option --tail requires a value"' || _increment_failures

    # restart must parse --no-build / --no-wait (start.sh resets the flags at
    # source time, so restart needs its own parser to honor them).
    _t "restart has parse_restart_args" bash -c 'DIR=.; source ./scripts/manage.d/restart.sh >/dev/null 2>&1; type -t parse_restart_args | grep -q function' || _increment_failures
    _t "restart --no-build accepted" bash -c './nukelabctl restart --no-build --help >/dev/null 2>&1' || _increment_failures
    _t "restart rejects unknown option" bash -c '! ./nukelabctl restart --bogus >/dev/null 2>&1' || _increment_failures

    # rm is normalized to remove at parse time (no dedicated dispatch case).
    _t "rm alias dispatches to remove" bash -c './nukelabctl rm --help | grep -q "Remove containers"' || _increment_failures
    _t "rm rejects unknown option" bash -c '! ./nukelabctl rm --bogus >/dev/null 2>&1' || _increment_failures

    # lint --fix / -f is accepted
    _t "lint --help lists --fix" bash -c './nukelabctl lint --help | grep -q -- "--fix"' || _increment_failures

    # loadtest help lists the k6 profiles
    _t "loadtest help lists k6-stress" bash -c './nukelabctl loadtest --help | grep -q "k6-stress"' || _increment_failures

    # Diagnostics commands
    _t "version command" bash -c './nukelabctl version | grep -q "NukeLab v2.0"' || _increment_failures
    _t "doctor command" bash -c './nukelabctl doctor --skip-port-check >/dev/null 2>&1' || _increment_failures

    # Error trap reports the failing command and location
    _t "ERR trap reports failure" bash -c './nukelabctl exec nonexistent true 2>&1 | grep -q "Command failed in"' || _increment_failures

    # Dev/prod isolation: separate state files and mutual exclusion helpers exist
    _t "prod/dev state files are separate" bash -c '
        source ./nukelabctl >/dev/null 2>&1 || true
        [ "$PROD_STATE_FILE" = "${DIR:-.}/.nukelab-state.sh" ] && [ "$DEV_STATE_FILE" = "${DIR:-.}/.nukelab-state-dev.sh" ]
    ' || _increment_failures
    _t "mutual exclusion helpers exist" bash -c '
        source ./nukelabctl >/dev/null 2>&1 || true
        type -t _is_stack_running | grep -q function && type -t _other_stack_running | grep -q function && type -t _require_other_stack_stopped | grep -q function
    ' || _increment_failures

    # Lint command help
    _t "command help: lint" bash -c './nukelabctl lint --help | grep -q "Run linters and format checks"' || _increment_failures

    echo ""
    if [ "$failures" -eq 0 ]; then
        ok "All self-tests passed"
    else
        die "$failures self-test(s) failed"
    fi
}
