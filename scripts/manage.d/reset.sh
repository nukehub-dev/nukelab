#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Default values for reset options.
RESET_YES=false

cmd_reset() {
    local _mode="PROD"
    $USE_DEV_MODE && _mode="DEV"

    # Resetting destroys all data of the active stack, so require explicit
    # confirmation. The only non-interactive bypass is --yes; never read from
    # a non-TTY (a failed `read` under set -e would dump the ERR trap).
    if ! $RESET_YES; then
        step "${RED}${BOLD}WARNING:${RESET} This deletes ALL data and containers of the ${BOLD}${_mode}${RESET} stack!"
        if [ ! -t 0 ]; then
            die "Reset of the ${_mode} stack requires confirmation, but stdin is not a terminal.\nPass --yes to confirm non-interactively."
        fi
        read -rp "Type 'yes' to confirm: " confirm || die "Confirmation required (no input); aborting."
        [[ "$confirm" = "yes" ]] || {
            info "Aborted."
            exit 0
        }
    fi

    log "Stopping everything..."
    kill_frontend
    if $COMPOSE "${COMPOSE_ARGS[@]}" down -v --remove-orphans; then
        log_debug "compose down completed"
    else
        warn "compose down returned an error; continuing with manual volume cleanup"
    fi

    # `down -v` already removes the project's own named volumes via labels. As
    # a fallback, remove any leftovers still carrying the compose project
    # label. Both the configured project name and the directory-derived
    # default are matched, because compose derives the project name from the
    # checkout directory unless COMPOSE_PROJECT_NAME is exported — volumes
    # created either way are found without hardcoding volume names.
    local _projects=("${COMPOSE_PROJECT_NAME:-nukelab}")
    local _dir_project
    _dir_project="$(basename "$DIR")"
    if [ "$_dir_project" != "${_projects[0]}" ]; then
        _projects+=("$_dir_project")
    fi

    local _p _vol
    for _p in "${_projects[@]}"; do
        while IFS= read -r _vol; do
            [ -n "$_vol" ] || continue
            $CONTAINER_ENGINE volume rm "$_vol" > /dev/null 2>&1 \
                || log_debug "Could not remove volume: $_vol"
        done < <($CONTAINER_ENGINE volume ls --filter "label=com.docker.compose.project=$_p" --format '{{.Name}}' 2> /dev/null)
    done

    clear_state
    ok "Reset complete"
}

parse_reset_args() {
    while [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; do
        case "${EXTRA_ARGS[0]}" in
            --yes | -y)
                RESET_YES=true
                EXTRA_ARGS=("${EXTRA_ARGS[@]:1}")
                ;;
            --help | -h)
                help_reset
                exit 0
                ;;
            --*)
                die "Unknown option for reset: ${EXTRA_ARGS[0]}"
                ;;
            *)
                die "Unexpected argument: ${EXTRA_ARGS[0]} (reset takes no target)"
                ;;
        esac
    done
}

help_reset() {
    cat <<- EOF
${BOLD}Usage:${RESET} ./nukelabctl reset [options]

⚠️  Delete ALL data, containers, and volumes of the current stack (PROD or
DEV, depending on the active mode). Requires typing 'yes' to confirm unless
--yes is given.

${BOLD}Options:${RESET}
  --yes, -y    Skip the confirmation prompt (for scripts)

${BOLD}Examples:${RESET}
  ./nukelabctl reset
  ./nukelabctl reset --yes
EOF
}
