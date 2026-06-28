#!/bin/bash
# Default values for lint options.
LINT_FIX=false

help_lint() {
    cat <<-EOF
${BOLD}Usage:${RESET} ./nukelabctl lint [target] [options]

Run linters and format checks.

${BOLD}Targets:${RESET}
  backend    Lint Python code with ruff ${DIM}(default if omitted)${RESET}
  frontend   Lint TypeScript/React code with eslint and prettier
  all        Lint both backend and frontend

${BOLD}Options:${RESET}
  --fix, -f       Auto-fix issues where possible
  --help, -h      Show this help

${BOLD}Examples:${RESET}
  ./nukelabctl lint
  ./nukelabctl lint backend --fix
  ./nukelabctl lint frontend
  ./nukelabctl lint all
EOF
}

parse_lint_args() {
    while [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; do
        case "${EXTRA_ARGS[0]}" in
            --fix|-f)
                LINT_FIX=true
                EXTRA_ARGS=("${EXTRA_ARGS[@]:1}")
                ;;
            --help|-h)
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

        if ! command -v npm >/dev/null 2>&1; then
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

    if [ $_exit -ne 0 ]; then
        die "Lint failed. Run './nukelabctl lint $TARGET --fix' to auto-fix where possible."
    fi

    ok "Lint passed"
}
