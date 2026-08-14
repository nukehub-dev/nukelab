#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Pre-populate a shared toolchain volume so server spawns are fast.
# The backend mounts these shared volumes read-only into workspace containers.

CACHE_TOOLCHAIN_SCRIPT="$DIR/scripts/environments/cache-toolchain.py"

parse_cache_toolchain_args() {
    for arg in "${EXTRA_ARGS[@]}"; do
        case "$arg" in
            --help | -h)
                help_cache_toolchain
                exit 0
                ;;
            --engine=*)
                CONTAINER_ENGINE="${arg#*=}"
                ;;
            --mount=*)
                CACHE_TOOLCHAIN_MOUNTS+=("${arg#*=}")
                ;;
            --force)
                CACHE_TOOLCHAIN_FORCE=1
                ;;
            *)
                if [ -z "$CACHE_TOOLCHAIN_IMAGE" ]; then
                    CACHE_TOOLCHAIN_IMAGE="$arg"
                else
                    die "Unknown extra argument for cache-toolchain: $arg"
                fi
                ;;
        esac
    done
}

cmd_cache_toolchain() {
    if [ -z "$CACHE_TOOLCHAIN_IMAGE" ]; then
        help_cache_toolchain
        exit 1
    fi

    if [ ! -f "$CACHE_TOOLCHAIN_SCRIPT" ]; then
        die "Cache toolchain script not found: $CACHE_TOOLCHAIN_SCRIPT"
    fi

    local _py
    _py=$(command -v python3 || command -v python || true)
    if [ -z "$_py" ]; then
        die "Python is required to run cache-toolchain."
    fi

    local _mount_args=()
    for _mount in "${CACHE_TOOLCHAIN_MOUNTS[@]}"; do
        _mount_args+=("--mount" "$_mount")
    done

    local _force_args=()
    if [ -n "${CACHE_TOOLCHAIN_FORCE:-}" ]; then
        _force_args+=("--force")
    fi

    if [ -n "${CONTAINER_ENGINE:-}" ]; then
        export CONTAINER_ENGINE
    fi

    step "Pre-populating toolchain volume for ${BOLD}${CACHE_TOOLCHAIN_IMAGE}${RESET}"
    "$_py" "$CACHE_TOOLCHAIN_SCRIPT" "${CACHE_TOOLCHAIN_IMAGE}" "${_mount_args[@]}" "${_force_args[@]}"
}

help_cache_toolchain() {
    cat <<- EOF
${BOLD}Usage:${RESET} ./nukelabctl cache-toolchain <image> [options]

Pre-populate a shared toolchain volume from a NukeLab toolchain image. This
makes the first server spawn on a node fast because the backend can mount an
already-populated volume instead of copying several gigabytes on every spawn.

${BOLD}Arguments:${RESET}
  <image>                 Toolchain image reference, e.g.
                          nukelab/radiation-transport:v1.2.3

${BOLD}Options:${RESET}
  --engine=<engine>       Container engine: docker or podman (default: auto)
  --mount=<path>          Path inside the image to copy (default: /opt/nuke)
  --force                 Wipe and re-populate the volume even if it is up to
                          date (e.g. after re-pushing an image tag)
  --help, -h              Show this help

${BOLD}Examples:${RESET}
  ./nukelabctl cache-toolchain nukelab/radiation-transport:v1.2.3
  ./nukelabctl cache-toolchain nukelab/openfoam:v2024 --mount=/opt/openfoam
EOF
}
