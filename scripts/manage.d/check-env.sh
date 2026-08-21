#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Default options for check-env.
CHECK_ENV_ALL=false
CHECK_ENV_CHANGED=false

cmd_check_env() {
    local target_files=()

    if $CHECK_ENV_ALL; then
        [ -f .env ] && target_files+=(".env")
        [ -f .env.development ] && target_files+=(".env.development")
    else
        if $USE_DEV_MODE && [ -f .env.development ]; then
            target_files+=(".env.development")
        elif [ -f .env ]; then
            target_files+=(".env")
        elif [ -f .env.development ]; then
            target_files+=(".env.development")
        else
            die "No environment file found.\n\n  cp .env.example .env.development"
        fi
    fi

    [ -f .env.example ] || die ".env.example not found"

    declare -A example_values
    _read_env_into_assoc .env.example example_values

    local exit_code=0
    for target in "${target_files[@]}"; do
        step "Checking ${target} against .env.example..."

        declare -A target_values
        _read_env_into_assoc "$target" target_values

        local missing=() stale=() changed=()

        for key in "${!example_values[@]}"; do
            if ! _assoc_has_key target_values "$key"; then
                missing+=("$key")
            fi
        done

        for key in "${!target_values[@]}"; do
            if ! _assoc_has_key example_values "$key"; then
                stale+=("$key")
            fi
        done

        if $CHECK_ENV_CHANGED; then
            for key in "${!target_values[@]}"; do
                if _assoc_has_key example_values "$key"; then
                    if [ "${target_values[$key]}" != "${example_values[$key]}" ]; then
                        changed+=("$key")
                    fi
                fi
            done
        fi

        if [ ${#missing[@]} -eq 0 ] && [ ${#stale[@]} -eq 0 ] && [ ${#changed[@]} -eq 0 ]; then
            ok "${target} is in sync with .env.example"
        else
            exit_code=1
            if [ ${#missing[@]} -gt 0 ]; then
                echo "${RED}✗${RESET}  Missing keys in ${target}:"
                printf '  - %s\n' "${missing[@]}" | sort
            fi
            if [ ${#stale[@]} -gt 0 ]; then
                echo "${YELLOW}⚠${RESET}  Stale keys in ${target} (removed from .env.example):"
                printf '  - %s\n' "${stale[@]}" | sort
            fi
            if [ ${#changed[@]} -gt 0 ]; then
                echo "${BLUE}▶${RESET} Changed values in ${target}:"
                printf '  - %s\n' "${changed[@]}" | sort
            fi
        fi
    done

    exit $exit_code
}

parse_check_env_args() {
    while [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; do
        case "${EXTRA_ARGS[0]}" in
            --all)
                CHECK_ENV_ALL=true
                EXTRA_ARGS=("${EXTRA_ARGS[@]:1}")
                ;;
            --changed)
                CHECK_ENV_CHANGED=true
                EXTRA_ARGS=("${EXTRA_ARGS[@]:1}")
                ;;
            --help | -h)
                help_check_env
                exit 0
                ;;
            --*)
                die "Unknown option for check-env: ${EXTRA_ARGS[0]}"
                ;;
            *)
                die "Unexpected argument for check-env: ${EXTRA_ARGS[0]}"
                ;;
        esac
    done
}

help_check_env() {
    cat <<- EOF
${BOLD}Usage:${RESET} ./nukelabctl check-env [options]

Compare .env / .env.development against the canonical .env.example template.
Reports missing keys, stale keys, and (with --changed) keys whose values differ
from the example defaults.

${BOLD}Options:${RESET}
  --all          Check both .env and .env.development if they exist
  --changed      Also report keys whose local value differs from .env.example
  --help, -h     Show this help

${BOLD}Examples:${RESET}
  ./nukelabctl check-env
  ./nukelabctl check-env --all --changed
EOF
}
