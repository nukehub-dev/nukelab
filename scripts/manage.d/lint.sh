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

DEV_VENV="${DIR}/backend/.venv-dev"

# Ensure the shared development venv exists and contains the tools from
# requirements-dev.txt. This venv is used by both `lint` and `security`.
_ensure_dev_venv() {
    if [ -x "${DEV_VENV}/bin/ruff" ] && [ -x "${DEV_VENV}/bin/bandit" ] && [ -x "${DEV_VENV}/bin/pip-audit" ]; then
        return 0
    fi

    log_warn "Dev tools not found; creating isolated venv at ${DEV_VENV}..."
    python3 -m venv "$DEV_VENV"
    "$DEV_VENV/bin/pip" install -q --upgrade pip
    "$DEV_VENV/bin/pip" install -q -r "$DIR/backend/requirements-dev.txt"

    if [ ! -x "${DEV_VENV}/bin/ruff" ]; then
        die "Failed to install dev tools. Install manually or check network access."
    fi
}

# Ensure ruff is available, installing it into the project-local dev venv if needed.
# Prints the absolute path to the ruff binary on stdout.
_ensure_ruff() {
    if command -v ruff >/dev/null 2>&1; then
        command -v ruff
        return 0
    fi

    _ensure_dev_venv
    echo "${DEV_VENV}/bin/ruff"
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
