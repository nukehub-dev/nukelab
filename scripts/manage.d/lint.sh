#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Default values for lint options.
LINT_FIX=false

help_lint() {
    cat <<- EOF
${BOLD}Usage:${RESET} ./nukelabctl lint [target] [options]

Run linters and format checks.

${BOLD}Targets:${RESET}
  backend    Lint Python code with ruff
  frontend   Lint TypeScript/React code with eslint and prettier
  shell      Lint shell scripts with shellcheck and shfmt
  markdown   Lint Markdown and check links with markdownlint-cli2 and lychee
  all        Lint backend, frontend, shell, and markdown ${DIM}(default)${RESET}

${BOLD}Options:${RESET}
  --fix, -f       Auto-fix issues where possible (backend + frontend; shfmt -w for shell)
  --help, -h      Show this help

${BOLD}Examples:${RESET}
  ./nukelabctl lint
  ./nukelabctl lint backend --fix
  ./nukelabctl lint frontend
  ./nukelabctl lint shell
  ./nukelabctl lint markdown
  ./nukelabctl lint all
EOF
}

parse_lint_args() {
    while [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; do
        case "${EXTRA_ARGS[0]}" in
            --fix | -f)
                LINT_FIX=true
                EXTRA_ARGS=("${EXTRA_ARGS[@]:1}")
                ;;
            --help | -h)
                help_lint
                exit 0
                ;;
            --*)
                die "Unknown option for lint: ${EXTRA_ARGS[0]}"
                ;;
            *)
                if [[ -z "${TARGET:-}" || "$TARGET" == "all" ]]; then
                    TARGET="${EXTRA_ARGS[0]}"
                    EXTRA_ARGS=("${EXTRA_ARGS[@]:1}")
                else
                    die "Unexpected argument: ${EXTRA_ARGS[0]}"
                fi
                ;;
        esac
    done

    if [[ -z "${TARGET:-}" ]]; then
        TARGET="all"
    fi
}

# Ensure ruff is available via the shared dev venv. _ensure_venv_tool is
# defined in lib.sh and prefers a global install before falling back.
# Prints the absolute path to the ruff binary on stdout.
_ensure_ruff() {
    _ensure_venv_tool ruff
}

cmd_lint() {
    local _exit=0

    if [ "$TARGET" = "backend" ] || [ "$TARGET" = "all" ]; then
        step "Linting backend..."

        local ruff_bin
        ruff_bin=$(_ensure_ruff)

        (
            cd "$DIR/backend"
            if $LINT_FIX; then
                "$ruff_bin" check --fix app tests || _exit=$?
                "$ruff_bin" format app tests || _exit=$?
            else
                "$ruff_bin" check app tests || _exit=$?
                "$ruff_bin" format --check app tests || _exit=$?
            fi
        )
    fi

    if [ "$TARGET" = "frontend" ] || [ "$TARGET" = "all" ]; then
        step "Linting frontend..."

        if ! command -v npm > /dev/null 2>&1; then
            die "npm not found. Install Node.js first."
        fi

        (
            cd "$DIR/frontend"
            [ -d node_modules ] || die "Run: ./nukelabctl install frontend"

            if $LINT_FIX; then
                npm run lint -- --fix || _exit=$?
                npm run format || _exit=$?
            else
                npm run lint || _exit=$?
                npm run format:check || _exit=$?
            fi
        )
    fi

    if [ "$TARGET" = "shell" ] || [ "$TARGET" = "all" ]; then
        step "Linting shell..."
        _lint_shell || _exit=$?
    fi

    if [ "$TARGET" = "markdown" ] || [ "$TARGET" = "all" ]; then
        step "Linting markdown..."
        _lint_markdown || _exit=$?
    fi

    if [ $_exit -ne 0 ]; then
        die "Lint failed. Run './nukelabctl lint $TARGET --fix' to auto-fix where possible."
    fi

    ok "Lint passed"
}

# Lint markdown files with markdownlint-cli2 and check internal/external links
# with lychee. When TARGET is "all", missing tools only warn so the default
# lint flow does not require Node-based markdown tooling. When TARGET is
# "markdown", missing tools are an error.
_lint_markdown() {
    local _exit=0
    local _explicit=false
    if [ "$TARGET" = "markdown" ]; then
        _explicit=true
    fi

    if ! command -v npx > /dev/null 2>&1; then
        if $_explicit; then
            err "npx not found. Install Node.js first."
            return 1
        fi
        warn "npx not found; skipping markdown lint (install Node.js to enable)"
        return 0
    fi

    if ! npx --yes markdownlint-cli2 --version > /dev/null 2>&1; then
        if $_explicit; then
            err "markdownlint-cli2 not available. Install with: npm install -g markdownlint-cli2"
            return 1
        fi
        warn "markdownlint-cli2 not available; skipping markdown lint"
        return 0
    fi

    if $LINT_FIX; then
        npx markdownlint-cli2 --fix '**/*.md' || _exit=$?
    else
        npx markdownlint-cli2 '**/*.md' || _exit=$?
    fi

    if ! command -v lychee > /dev/null 2>&1; then
        if $_explicit; then
            err "lychee not found. Install from https://lychee.cli.rs or use the docs CI workflow."
            return 1
        fi
        warn "lychee not found; skipping link check (CI still runs it)"
        return $_exit
    fi

    lychee --no-progress \
        --exclude-loopback \
        --exclude-path node_modules \
        --exclude-path backend/.venv-dev \
        --exclude-path backend/.venv \
        --exclude-path frontend/node_modules \
        --exclude-path frontend/test-results \
        --exclude-path frontend/dist \
        -- '*.md' 'docs/**/*.md' || _exit=$?

    return $_exit
}

# Lint all shell scripts under nukelabctl / scripts/ / environments/ and
# check shfmt formatting against .editorconfig. With --fix, applies shfmt -w
# in place (shellcheck findings are reported but not auto-fixed — its
# auto-fixer is opt-in per-rule and rarely safe to apply blindly).
_lint_shell() {
    local _exit=0
    local _shell_files=(nukelabctl scripts/lib.sh scripts/nukelabctl-completion.bash)
    local f

    # Collect every .sh under scripts/ and environments/ so new subdirectories
    # (e.g. scripts/environments, scripts/services) are linted automatically.
    while IFS= read -r -d '' f; do
        _shell_files+=("$f")
    done < <(find scripts environments -type f -name '*.sh' -print0 | sort -z)

    # The static analyzer is run in two passes: errors fail the lint, warnings
    # are surfaced but non-fatal because many are cross-file false positives
    # (e.g. SC2034 "appears unused" for globals consumed by sourced modules).
    if command -v shellcheck > /dev/null 2>&1; then
        local _sc_out
        if _sc_out=$(shellcheck -S error "${_shell_files[@]}" 2>&1); then
            ok "shellcheck: no errors"
        else
            err "shellcheck: errors found"
            printf '%s\n' "$_sc_out" >&2
            err "Run for details: shellcheck -S error nukelabctl scripts/"
            _exit=1
        fi
        # Surface warnings for review without failing.
        local _sc_warns
        if _sc_warns=$(shellcheck -S warning "${_shell_files[@]}" 2>&1); then
            :
        else
            local _warn_count
            _warn_count=$(printf '%s\n' "$_sc_warns" | grep -c '^In ' || true)
            if [ "${_warn_count:-0}" -gt 0 ]; then
                warn "shellcheck: $_warn_count warning(s) (non-blocking). Run to see: shellcheck -S warning nukelabctl scripts/"
            fi
        fi
    else
        warn "shellcheck not installed; skipping (install for stronger shell linting)"
    fi

    # shfmt — checks formatting against .editorconfig. --fix applies shfmt -w.
    if command -v shfmt > /dev/null 2>&1; then
        local _fmt_diff
        if $LINT_FIX; then
            shfmt -w "${_shell_files[@]}" && ok "shfmt: applied formatting"
            # Re-check to make sure nothing remains.
            if _fmt_diff=$(shfmt -d "${_shell_files[@]}" 2>&1); then
                :
            else
                err "shfmt: still has diff after --fix (file a bug)"
                _exit=1
            fi
        else
            if _fmt_diff=$(shfmt -d "${_shell_files[@]}" 2>&1); then
                ok "shfmt: style matches .editorconfig"
            else
                local _fmt_count
                _fmt_count=$(shfmt -l "${_shell_files[@]}" 2> /dev/null | wc -l || true)
                _fmt_count=${_fmt_count// /}
                err "shfmt: $_fmt_count file(s) need formatting"
                { printf '%s\n' "$_fmt_diff" | head -40 >&2 || true; }
                err "Apply with: ./nukelabctl lint shell --fix"
                _exit=1
            fi
        fi
    else
        warn "shfmt not installed; skipping (install for shell formatting)"
    fi

    return $_exit
}
