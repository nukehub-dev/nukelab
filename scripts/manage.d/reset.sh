#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

cmd_reset() {
    step "${RED}${BOLD}WARNING:${RESET} This deletes ALL data and containers!"
    read -rp "Type 'yes' to confirm: " confirm
    [[ "$confirm" = "yes" ]] || {
        info "Aborted."
        exit 0
    }

    log "Stopping everything..."
    kill_frontend
    if $COMPOSE "${COMPOSE_ARGS[@]}" down -v --remove-orphans; then
        log_debug "compose down completed"
    else
        warn "compose down returned an error; continuing with manual volume cleanup"
    fi

    # Derive named volumes from the active compose configuration so reset
    # never misses a volume that was added upstream. Best-effort: fall back
    # to the historical hardcoded list if `compose config --volumes` fails
    # (e.g. compose plugin missing on a partial install).
    local _volumes=()
    if _vol_out=$($COMPOSE "${COMPOSE_ARGS[@]}" config --volumes 2> /dev/null); then
        while IFS= read -r line; do
            [ -n "$line" ] && _volumes+=("$line")
        done <<< "$_vol_out"
    fi
    if [ ${#_volumes[@]} -eq 0 ]; then
        _volumes=(nukelab-postgres-data nukelab-letsencrypt)
        log_debug "Falling back to hardcoded volume list: ${_volumes[*]}"
    fi

    # Prefix with the active project name if compose plugin emitted bare names.
    # Both docker compose and podman-compose typically already prefix them, so
    # we try the reported name first and then the prefixed form.
    for vol in "${_volumes[@]}"; do
        if $CONTAINER_ENGINE volume inspect "$vol" > /dev/null 2>&1; then
            $CONTAINER_ENGINE volume rm "$vol" > /dev/null 2>&1 \
                || log_debug "Could not remove volume: $vol"
        elif $CONTAINER_ENGINE volume inspect "${COMPOSE_PROJECT_NAME:-nukelab}_$vol" > /dev/null 2>&1; then
            $CONTAINER_ENGINE volume rm "${COMPOSE_PROJECT_NAME:-nukelab}_$vol" > /dev/null 2>&1 \
                || log_debug "Could not remove volume: ${COMPOSE_PROJECT_NAME:-nukelab}_$vol"
        fi
    done

    clear_state
    ok "Reset complete"
}

help_reset() {
    cat <<- EOF
${BOLD}Usage:${RESET} ./nukelabctl reset

⚠️  Delete ALL data, containers, and volumes. Requires confirmation.

${BOLD}Examples:${RESET}
  ./nukelabctl reset
EOF
}
