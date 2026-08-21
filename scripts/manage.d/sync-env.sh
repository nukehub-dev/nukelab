#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Default options for sync-env.
SYNC_ENV_DRY_RUN=false
SYNC_ENV_YES=false
SYNC_ENV_TARGET=""

cmd_sync_env() {
    local target="${SYNC_ENV_TARGET}"

    if [ -z "$target" ]; then
        if $USE_DEV_MODE && [ -f .env.development ]; then
            target=".env.development"
        elif [ -f .env ]; then
            target=".env"
        elif [ -f .env.development ]; then
            target=".env.development"
        else
            die "No environment file found.\n\n  cp .env.example .env.development"
        fi
    fi

    [ -f .env.example ] || die ".env.example not found"
    [ "$target" = ".env.example" ] && die "Cannot sync .env.example into itself"

    declare -A example_values
    _read_env_into_assoc .env.example example_values

    declare -A target_values
    _read_env_into_assoc "$target" target_values

    local to_add=()
    for key in "${!example_values[@]}"; do
        if ! _assoc_has_key target_values "$key"; then
            to_add+=("$key")
        fi
    done

    local stale=()
    for key in "${!target_values[@]}"; do
        if ! _assoc_has_key example_values "$key"; then
            stale+=("$key")
        fi
    done

    if [ ${#to_add[@]} -eq 0 ] && [ ${#stale[@]} -eq 0 ]; then
        ok "${target} is already in sync with .env.example"
        return 0
    fi

    if [ ${#to_add[@]} -gt 0 ]; then
        echo "${BLUE}▶${RESET} Keys to add to ${target}:"
        printf '  + %s\n' "${to_add[@]}" | sort
    fi
    if [ ${#stale[@]} -gt 0 ]; then
        echo "${YELLOW}⚠${RESET}  Stale keys in ${target} (not removed, delete manually if desired):"
        printf '  - %s\n' "${stale[@]}" | sort
    fi

    if $SYNC_ENV_DRY_RUN; then
        echo "${BLUE}▶${RESET} Dry run: no changes written"
        return 0
    fi

    if ! $SYNC_ENV_YES; then
        local reply
        read -r -p "Append missing keys to ${target}? [y/N] " reply
        if [[ ! "$reply" =~ ^[Yy]$ ]]; then
            echo "${BLUE}▶${RESET} Aborted"
            return 0
        fi
    fi

    {
        echo ""
        echo "# ============================================================================="
        echo "# SYNCED FROM .env.example — $(date -Iseconds)"
        echo "# ============================================================================="
        for key in "${to_add[@]}"; do
            echo "${key}=${example_values[$key]}"
        done
    } >> "$target"

    ok "Appended ${#to_add[@]} missing key(s) to ${target}"
}

parse_sync_env_args() {
    while [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; do
        case "${EXTRA_ARGS[0]}" in
            --dry-run)
                SYNC_ENV_DRY_RUN=true
                EXTRA_ARGS=("${EXTRA_ARGS[@]:1}")
                ;;
            --yes | -y)
                SYNC_ENV_YES=true
                EXTRA_ARGS=("${EXTRA_ARGS[@]:1}")
                ;;
            --help | -h)
                help_sync_env
                exit 0
                ;;
            --*)
                die "Unknown option for sync-env: ${EXTRA_ARGS[0]}"
                ;;
            *)
                if [ -z "${SYNC_ENV_TARGET}" ]; then
                    SYNC_ENV_TARGET="${EXTRA_ARGS[0]}"
                    EXTRA_ARGS=("${EXTRA_ARGS[@]:1}")
                else
                    die "Unexpected argument for sync-env: ${EXTRA_ARGS[0]}"
                fi
                ;;
        esac
    done
}

help_sync_env() {
    cat <<- EOF
${BOLD}Usage:${RESET} ./nukelabctl sync-env [file] [options]

Non-destructively merge missing keys from .env.example into a local env file.
Existing keys and their values are never overwritten, so secrets and local
overrides stay intact. Stale keys are reported but left in place.

${BOLD}Arguments:${RESET}
  file           Target env file (default: active env file)

${BOLD}Options:${RESET}
  --dry-run      Show what would be added without writing anything
  --yes, -y      Skip the confirmation prompt
  --help, -h     Show this help

${BOLD}Examples:${RESET}
  ./nukelabctl sync-env
  ./nukelabctl sync-env .env.development --dry-run
  ./nukelabctl sync-env .env --yes
EOF
}
