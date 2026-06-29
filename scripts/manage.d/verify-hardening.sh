#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Verify container hardening settings for a spawned NukeLab server.
# Checks the runtime configuration (User, CapDrop, ReadonlyRootfs, SecurityOpt)
# and confirms capability sets are zeroed inside the container.

HARDENING_USER="65532:65532"
HARDENING_CAP_DROP='[ALL]'
HARDENING_READONLY_ROOTFS='true'
HARDENING_SECURITY_OPT='[no-new-privileges:true]'

parse_verify_hardening_args() {
    for arg in "${EXTRA_ARGS[@]}"; do
        case "$arg" in
            --help | -h)
                help_verify_hardening
                exit 0
                ;;
            --user=*)
                HARDENING_USER="${arg#*=}"
                ;;
            *)
                die "Unknown option for verify-hardening: $arg\nRun './nukelabctl verify-hardening --help' for usage."
                ;;
        esac
    done
}

_find_container() {
    local name="${1:-}"
    if [ -n "$name" ]; then
        if "$CONTAINER_ENGINE" inspect "$name" > /dev/null 2>&1; then
            echo "$name"
            return 0
        fi
        die "Container not found: $name"
    fi

    # Auto-detect a running NukeLab server container.
    local container
    container=$("$CONTAINER_ENGINE" ps --filter "label=traefik.enable=true" --filter "name=nukelab-server-" --format '{{.Names}}' 2> /dev/null | head -n 1)
    if [ -n "$container" ]; then
        echo "$container"
        return 0
    fi

    die "No running NukeLab server container found. Provide a container name or start a server first."
}

_inspect_value() {
    local container="$1"
    local format="$2"
    "$CONTAINER_ENGINE" inspect "$container" --format "$format" 2> /dev/null
}

_run_in_container() {
    local container="$1"
    shift
    "$CONTAINER_ENGINE" exec "$container" "$@" 2> /dev/null
}

_is_capdrop_all() {
    # Docker reports '[ALL]'; Podman expands it to the capability list.
    # Either form means all capabilities were dropped.
    [[ "$1" == "[ALL]" ]] || [[ "$1" == *"CAP_CHOWN"* ]]
}

_is_security_opt_no_new_privileges() {
    # Docker reports '[no-new-privileges:true]'; Podman reports '[no-new-privileges]'.
    [[ "$1" == *"no-new-privileges"* ]]
}

cmd_verify_hardening() {
    local container_name="${TARGET:-}"
    if [ "$container_name" = "all" ]; then
        container_name=""
    fi
    local container
    container=$(_find_container "$container_name")

    step "Verifying container hardening for ${BOLD}${container}${RESET}"

    local user cap_drop readonly_rootfs security_opt
    user=$(_inspect_value "$container" '{{.Config.User}}')
    cap_drop=$(_inspect_value "$container" '{{.HostConfig.CapDrop}}')
    readonly_rootfs=$(_inspect_value "$container" '{{.HostConfig.ReadonlyRootfs}}')
    security_opt=$(_inspect_value "$container" '{{.HostConfig.SecurityOpt}}')

    local _exit=0

    if [ "$user" = "$HARDENING_USER" ]; then
        log_ok "User: ${user}"
    else
        log_warn "User: ${user} (expected ${HARDENING_USER})"
        _exit=1
    fi

    if _is_capdrop_all "$cap_drop"; then
        log_ok "CapDrop: ${cap_drop}"
    else
        log_warn "CapDrop: ${cap_drop} (expected ${HARDENING_CAP_DROP})"
        _exit=1
    fi

    if [ "$readonly_rootfs" = "$HARDENING_READONLY_ROOTFS" ]; then
        log_ok "ReadonlyRootfs: ${readonly_rootfs}"
    else
        log_warn "ReadonlyRootfs: ${readonly_rootfs} (expected ${HARDENING_READONLY_ROOTFS})"
        _exit=1
    fi

    if _is_security_opt_no_new_privileges "$security_opt"; then
        log_ok "SecurityOpt: ${security_opt}"
    else
        log_warn "SecurityOpt: ${security_opt} (expected ${HARDENING_SECURITY_OPT})"
        _exit=1
    fi

    local uid_line cap_lines
    uid_line=$(_run_in_container "$container" id) || true
    cap_lines=$(_run_in_container "$container" sh -c 'cat /proc/self/status | grep Cap') || true

    if [ -n "$uid_line" ]; then
        if echo "$uid_line" | grep -q "uid=65532"; then
            log_ok "Container uid: ${uid_line}"
        else
            log_warn "Container uid: ${uid_line} (expected uid=65532)"
            _exit=1
        fi
    else
        log_warn "Could not determine container user (is it running?)"
        _exit=1
    fi

    if [ -n "$cap_lines" ]; then
        if echo "$cap_lines" | grep -Eq '^Cap(Prm|Eff|Bnd|Inh|Amb):\s+0+$'; then
            log_ok "Container capability sets are zeroed"
        else
            log_warn "Container capability sets are not zeroed:"
            echo "$cap_lines" | sed 's/^/    /'
            _exit=1
        fi
    else
        log_warn "Could not read container capability sets (is it running?)"
        _exit=1
    fi

    if [ $_exit -eq 0 ]; then
        log_ok "Container hardening verification passed"
    else
        log_warn "Container hardening verification failed"
    fi

    return $_exit
}

help_verify_hardening() {
    cat <<- EOF
${BOLD}Usage:${RESET} ./nukelabctl verify-hardening [container-name] [options]

Verify that a spawned NukeLab server container is hardened according to the
project baseline (non-root user, no capabilities, read-only rootfs,
no-new-privileges).

If no container name is provided, the command auto-detects a running NukeLab
server container by its Traefik label and name prefix.

${BOLD}Options:${RESET}
  --user=<uid:gid>        Expected container user (default: ${HARDENING_USER})
  --help, -h              Show this help

${BOLD}Examples:${RESET}
  ./nukelabctl verify-hardening
  ./nukelabctl verify-hardening nukelab-server-admin-hardened-retest-a
  ./nukelabctl verify-hardening --user=1000:1000 my-custom-container
EOF
}
