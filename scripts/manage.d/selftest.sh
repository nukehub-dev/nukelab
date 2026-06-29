#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

help_selftest() {
    cat <<- EOF
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
    if "$@" > /dev/null 2>&1; then
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
    if ./nukelabctl logs --tail abc --no-follow backend > /dev/null 2>&1; then
        err "invalid --tail value not rejected"
        _increment_failures
    else
        ok "invalid --tail value rejected"
    fi

    if ./nukelabctl stop --timeout abc > /dev/null 2>&1; then
        err "invalid --timeout value not rejected"
        _increment_failures
    else
        ok "invalid --timeout value rejected"
    fi

    # Unknown options are rejected
    if ./nukelabctl logs --bogus > /dev/null 2>&1; then
        err "unknown option not rejected"
        _increment_failures
    else
        ok "unknown option rejected"
    fi

    # --dev global flag was removed; dev is now a meta-command
    if ./nukelabctl start --dev > /dev/null 2>&1; then
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
    _t "lint --help lists shell target" bash -c './nukelabctl lint --help | grep -q "shell      Lint shell"' || _increment_failures
    _t "lint --help lists markdown target" bash -c './nukelabctl lint --help | grep -q "markdown   Lint Markdown"' || _increment_failures
    _t "lint shell passes (style + static analysis)" bash -c './nukelabctl lint shell >/dev/null 2>&1' || _increment_failures
    _t "lint markdown passes when tools are present" bash -c './nukelabctl lint markdown >/dev/null 2>&1' || _increment_failures

    # Security command behaviors
    _t "security --help lists --no-fail-on-high" bash -c './nukelabctl security --help | grep -q -- "--no-fail-on-high"' || _increment_failures
    _t "security --help mentions .venv-dev" bash -c './nukelabctl security --help | grep -q ".venv-dev"' || _increment_failures
    _t "security rejects unknown option" bash -c '! ./nukelabctl security --bogus >/dev/null 2>&1' || _increment_failures

    # verify-hardening command
    _t "verify-hardening help" bash -c './nukelabctl verify-hardening --help | grep -q "Verify that a spawned NukeLab server container is hardened"' || _increment_failures
    _t "verify-hardening rejects unknown option" bash -c '! ./nukelabctl verify-hardening --bogus >/dev/null 2>&1' || _increment_failures
    _t "verify-hardening fails for missing container" bash -c '! ./nukelabctl verify-hardening definitely-not-a-real-container-12345 >/dev/null 2>&1' || _increment_failures

    # update --cache is accepted
    _t "update --help mentions --cache" bash -c './nukelabctl update --help | grep -q -- "--cache"' || _increment_failures
    _t "update rejects unknown option" bash -c '! ./nukelabctl update --bogus >/dev/null 2>&1' || _increment_failures

    # e2e forwards argv (help text documents this)
    _t "e2e --help documents playwright-args passthrough" bash -c './nukelabctl e2e --help | grep -q "playwright-args"' || _increment_failures

    # Shared dev venv helper now lives in lib.sh (drift guard for lint/security)
    _t "lib.sh exposes _ensure_venv_tool" bash -c 'DIR=.; source ./scripts/lib.sh >/dev/null 2>&1; type -t _ensure_venv_tool | grep -q function' || _increment_failures

    # stale doctor logic tightened to require a real socket
    _t "doctor --skip-port-check still runs" bash -c './nukelabctl doctor --skip-port-check >/dev/null 2>&1' || _increment_failures

    # The static-analysis tool is the strongest checker for shell scripts; warn
    # (not fail) when it is missing so CI can still run without it.
    if command -v shellcheck > /dev/null 2>&1; then
        local _sc_files=(nukelabctl scripts/lib.sh scripts/nukelabctl-completion.bash)
        for f in scripts/manage.d/*.sh; do
            _sc_files+=("$f")
        done
        # Only fail the self-test on ERROR-severity findings (e.g. SC2148
        # missing shebang, unbound variables, parses failures). The repo has
        # pre-existing warning/info-level notes — many are cross-file false
        # positives (e.g. SC2034 "appears unused" for globals used in other
        # sourced modules) or stylistic. Those are surfaced for review via
        # `shellcheck <files>` directly but shouldn't gate CI.
        local _sc_out _sc_rc
        _sc_out=$(shellcheck -S error "${_sc_files[@]}" 2>&1) && _sc_rc=0 || _sc_rc=$?
        if [ $_sc_rc -eq 0 ]; then
            ok "shellcheck clean (no errors)"
        else
            err "shellcheck reported errors:"
            printf '%s\n' "$_sc_out" >&2
            err "Run for details: shellcheck -S error nukelabctl scripts/"
            _increment_failures
        fi
    else
        warn "shellcheck not installed; skipping static analysis (install shellcheck for stronger checks)"
    fi

    # shfmt is the shell equivalent of ruff/prettier; it reads .editorconfig.
    # Strict by default so format drift fails CI/local self-test just like a
    # failing ruff check would. Set NUKELAB_STRICT_FMT=0 to downgrade to a
    # warning (handy when prototyping).
    if command -v shfmt > /dev/null 2>&1; then
        local _fmt_files=(nukelabctl scripts/lib.sh scripts/nukelabctl-completion.bash)
        for f in scripts/manage.d/*.sh; do
            _fmt_files+=("$f")
        done
        local _fmt_diff
        if _fmt_diff=$(shfmt -d "${_fmt_files[@]}" 2>&1); then
            ok "shfmt clean (style matches .editorconfig)"
        else
            # `shfmt -l` returns non-zero when files need reformatting; that
            # non-zero halts the script under `set -E`, so absorb with `|| true`.
            local _fmt_count
            _fmt_count=$(shfmt -l "${_fmt_files[@]}" 2> /dev/null | wc -l || true)
            _fmt_count=${_fmt_count// /}
            if [ "${NUKELAB_STRICT_FMT:-1}" = "1" ]; then
                err "shfmt reports $_fmt_count file(s) needing format:"
                # Truncate long diffs safely: `head` closing early can SIGPIPE
                # the upstream `printf` and trip the ERR trap, so absorb it.
                { printf '%s\n' "$_fmt_diff" | head -40 >&2 || true; }
                err "Apply with: ./nukelabctl lint shell --fix"
                _increment_failures
            else
                warn "shfmt reports $_fmt_count file(s) needing format (non-blocking; NUKELAB_STRICT_FMT=0)"
                warn "Apply formatting with: shfmt -w ${_fmt_files[*]}"
            fi
        fi
    else
        warn "shfmt not installed; skipping style check (install shfmt for the shell equivalent of ruff/prettier)"
    fi

    echo ""
    if [ "$failures" -eq 0 ]; then
        ok "All self-tests passed"
    else
        die "$failures self-test(s) failed"
    fi
}
