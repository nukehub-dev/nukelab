#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

source "$DIR/scripts/manage.d/stop.sh"
source "$DIR/scripts/manage.d/start.sh"

# parse_restart_args mirrors parse_start_args so that --no-build / --no-wait
# are honored. start.sh resets START_BUILD/START_WAIT to true at source time,
# so without this parser restart silently rebuilds and waits.
parse_restart_args() {
    while [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; do
        case "${EXTRA_ARGS[0]}" in
            --no-build)
                START_BUILD=false
                EXTRA_ARGS=("${EXTRA_ARGS[@]:1}")
                ;;
            --no-wait)
                START_WAIT=false
                EXTRA_ARGS=("${EXTRA_ARGS[@]:1}")
                ;;
            --help | -h)
                help_restart
                exit 0
                ;;
            --*)
                die "Unknown option for restart: ${EXTRA_ARGS[0]}"
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
}

cmd_restart() {
    cmd_stop
    sleep 2
    cmd_start
}

help_restart() {
    cat <<- EOF
${BOLD}Usage:${RESET} ./nukelabctl restart [target]

Stop and then start services.

${BOLD}Targets:${RESET} backend | frontend | all

${BOLD}Examples:${RESET}
  ./nukelabctl restart
  ./nukelabctl restart backend
EOF
}
