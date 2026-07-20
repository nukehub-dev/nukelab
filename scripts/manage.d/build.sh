#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

BUILD_ARGS=()

parse_build_args() {
    local _filtered=()
    BUILD_ARGS=()

    for _arg in "${EXTRA_ARGS[@]}"; do
        case "$_arg" in
            --no-cache)
                BUILD_ARGS+=(--no-cache)
                ;;
            --help | -h)
                help_build
                exit 0
                ;;
            --*)
                die "Unknown option for build: $_arg"
                ;;
            *)
                _filtered+=("$_arg")
                ;;
        esac
    done

    EXTRA_ARGS=("${_filtered[@]}")

    case "$TARGET" in
        backend | frontend | env | all) ;;
        *)
            die "Unknown target for build: $TARGET\nRun './nukelabctl build --help' for usage."
            ;;
    esac
}

cmd_build() {
    setup_cpu_lib_volume

    step "Building..."

    if [ "$TARGET" = "env" ]; then
        _build_environments
        ok "Environment build complete"
        return
    fi

    if [ "$TARGET" = "backend" ] || [ "$TARGET" = "all" ]; then
        log "Building backend containers..."
        _run_quiet_unless_verbose $COMPOSE "${COMPOSE_ARGS[@]}" build "${BUILD_ARGS[@]}" backend celery-worker celery-beat
        log "Building backend test container..."
        _run_quiet_unless_verbose $COMPOSE --profile test "${COMPOSE_ARGS[@]}" build "${BUILD_ARGS[@]}" backend-test
    fi

    if [ "$TARGET" = "frontend" ] || [ "$TARGET" = "all" ]; then
        log "Building frontend container..."
        _run_quiet_unless_verbose $COMPOSE "${COMPOSE_ARGS[@]}" build "${BUILD_ARGS[@]}" frontend
    fi

    ok "Build complete"
}

_build_environments() {
    local _envs=()

    if [ ${#EXTRA_ARGS[@]} -eq 0 ]; then
        die "No environment specified. Usage: ./nukelabctl build env <name> [--no-cache]"
    fi

    for _env in "${EXTRA_ARGS[@]}"; do
        case "$_env" in
            -*)
                # Stop at the first flag; positional environment names are done.
                break
                ;;
            *)
                _envs+=("$_env")
                ;;
        esac
    done

    if [ ${#_envs[@]} -eq 0 ]; then
        die "No environment specified. Usage: ./nukelabctl build env <name> [--no-cache]"
    fi

    # Expand "all" to the full environment build set in dependency order.
    local _expanded=()
    local _has_all=false
    for _env in "${_envs[@]}"; do
        if [ "$_env" = "all" ]; then
            _has_all=true
            break
        fi
    done
    if $_has_all; then
        _envs=(base workspace radiation-transport gpu dev)
    fi

    for _env in "${_envs[@]}"; do
        local _script="$DIR/scripts/environments/build-$_env.sh"
        if [ ! -f "$_script" ]; then
            die "Unknown environment: $_env (no $_script)"
        fi
        log "Building environment: $_env"
        _run_quiet_unless_verbose bash "$_script" "${BUILD_ARGS[@]}"
    done
}

help_build() {
    cat <<- EOF
${BOLD}Usage:${RESET} ./nukelabctl build [target]
       ./nukelabctl build env <name> [name...] [--no-cache]

Build container images.

${BOLD}Targets:${RESET} backend | frontend | all | env <name>

${BOLD}Environment names:${RESET} base | workspace | radiation-transport | gpu | dev | all

${BOLD}Options:${RESET}
  --no-cache    Build without reusing the container layer cache.

${BOLD}Examples:${RESET}
  ./nukelabctl build
  ./nukelabctl build backend
  ./nukelabctl build frontend
  ./nukelabctl build env base
  ./nukelabctl build env radiation-transport
  ./nukelabctl build env base workspace radiation-transport
  ./nukelabctl build env workspace --no-cache

${BOLD}Note:${RESET} The default ./nukelabctl build (and all) only builds backend/frontend
compose images. Environment images are built separately with env NAME.
EOF
}
