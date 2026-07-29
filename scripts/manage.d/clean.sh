#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Default values for clean options.
CLEAN_YES=false

cmd_clean() {
    # Compose labels every resource it creates with the project name, so prunes
    # can be scoped to NukeLab instead of the whole engine. Cover both stacks
    # and the directory-derived default (used when COMPOSE_PROJECT_NAME is not
    # exported) so resources created either way still match.
    local _projects=()
    local _p
    for _p in "${PROD_PROJECT_NAME:-nukelab}" "${DEV_PROJECT_NAME:-nukelab-dev}" "$(basename "$DIR")"; do
        [[ " ${_projects[*]} " == *" $_p "* ]] && continue
        _projects+=("$_p")
    done

    if ! $CLEAN_YES; then
        step "${RED}${BOLD}WARNING:${RESET} This removes unused container-engine resources:"
        log "  - stopped containers, dangling images, dangling volumes ${DIM}(projects: ${_projects[*]})${RESET}"
        log "  - build cache ${DIM}(engine-wide, not project-scoped)${RESET}"
        if [ ! -t 0 ]; then
            die "Clean requires confirmation, but stdin is not a terminal.\nPass --yes to confirm non-interactively."
        fi
        read -rp "Type 'yes' to confirm: " confirm || die "Confirmation required (no input); aborting."
        [[ "$confirm" = "yes" ]] || {
            info "Aborted."
            exit 0
        }
    fi

    step "Cleaning up..."

    log "Removing stopped containers..."
    for _p in "${_projects[@]}"; do
        $CONTAINER_ENGINE container prune -f --filter "label=com.docker.compose.project=$_p" 2> /dev/null || true
    done

    log "Removing dangling images..."
    for _p in "${_projects[@]}"; do
        $CONTAINER_ENGINE image prune -f --filter "label=com.docker.compose.project=$_p" 2> /dev/null || true
    done

    log "Removing dangling volumes..."
    for _p in "${_projects[@]}"; do
        $CONTAINER_ENGINE volume prune -f --filter "label=com.docker.compose.project=$_p" 2> /dev/null || true
    done

    # builder prune cannot be scoped by label; it is covered by the
    # confirmation above and noted as engine-wide there.
    log "Removing build cache..."
    $CONTAINER_ENGINE builder prune -f 2> /dev/null || true

    # Only clear local runtime state when no stack is running; wiping it under
    # a live stack would orphan the saved compose configuration.
    if _is_stack_running; then
        warn "A stack is still running; keeping local runtime state files."
    else
        log "Removing local runtime state files..."
        clear_state
    fi

    ok "Cleanup complete"
}

parse_clean_args() {
    while [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; do
        case "${EXTRA_ARGS[0]}" in
            --yes | -y)
                CLEAN_YES=true
                EXTRA_ARGS=("${EXTRA_ARGS[@]:1}")
                ;;
            --help | -h)
                help_clean
                exit 0
                ;;
            --*)
                die "Unknown option for clean: ${EXTRA_ARGS[0]}"
                ;;
            *)
                die "Unexpected argument: ${EXTRA_ARGS[0]} (clean takes no target)"
                ;;
        esac
    done
}

help_clean() {
    cat <<- EOF
${BOLD}Usage:${RESET} ./nukelabctl clean [options]

Remove this project's stopped containers, dangling images, and dangling
volumes (scoped by the compose project label), plus the engine-wide build
cache. Requires typing 'yes' to confirm unless --yes is given. Local runtime
state files are removed only when no stack is running.

${BOLD}Options:${RESET}
  --yes, -y    Skip the confirmation prompt (for scripts)

${BOLD}Examples:${RESET}
  ./nukelabctl clean
  ./nukelabctl clean --yes
EOF
}
