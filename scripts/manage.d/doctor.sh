#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

help_doctor() {
    cat <<- EOF
${BOLD}Usage:${RESET} ./nukelabctl doctor [options]

Run non-destructive checks and report whether the host environment is ready
to run NukeLab.

Also reports read-only recovery-journal and registry-verification preflight
state. A stopped stack or unreachable database is reported as unavailable,
not as a failure.

${BOLD}Options:${RESET}
  --post-upgrade             Verify a running upgraded stack (read-only)
  --expected-version <ver>   Release version required by --post-upgrade
                             (default: resolved NUKELAB_VERSION/VERSION/git tag)
  --help, -h                 Show this help

${BOLD}Post-upgrade mode checks:${RESET}
required service containers, public API health and release version, running
service image identity, database schema head compatibility, Celery worker
heartbeat and Beat presence, unresolved recovery rows, and optional batch-job
tables. It never migrates, writes, restarts, pulls, or prints credentials.

Exit status is 0 when all required checks pass and 1 when any required check
fails. Warnings require review but do not fail the run.

${BOLD}Examples:${RESET}
  ./nukelabctl doctor
  ./nukelabctl doctor --verbose
  ./nukelabctl doctor --post-upgrade
  ./nukelabctl doctor --post-upgrade --expected-version 2.4.0
EOF
}

# Defaults for doctor options.
DOCTOR_POST_UPGRADE=false
DOCTOR_EXPECTED_VERSION=""

parse_doctor_args() {
    while [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; do
        case "${EXTRA_ARGS[0]}" in
            --post-upgrade)
                DOCTOR_POST_UPGRADE=true
                EXTRA_ARGS=("${EXTRA_ARGS[@]:1}")
                ;;
            --expected-version)
                if [ ${#EXTRA_ARGS[@]} -lt 2 ] || [ -z "${EXTRA_ARGS[1]}" ]; then
                    die "Missing value for doctor --expected-version"
                fi
                DOCTOR_EXPECTED_VERSION="${EXTRA_ARGS[1]}"
                EXTRA_ARGS=("${EXTRA_ARGS[@]:2}")
                ;;
            --expected-version=*)
                DOCTOR_EXPECTED_VERSION="${EXTRA_ARGS[0]#*=}"
                if [ -z "$DOCTOR_EXPECTED_VERSION" ]; then
                    die "Missing value for doctor --expected-version"
                fi
                EXTRA_ARGS=("${EXTRA_ARGS[@]:1}")
                ;;
            --help | -h)
                help_doctor
                exit 0
                ;;
            --*)
                die "Unknown option for doctor: ${EXTRA_ARGS[0]}"
                ;;
            *)
                die "Unexpected argument for doctor: ${EXTRA_ARGS[0]}"
                ;;
        esac
    done

    if [ -n "$DOCTOR_EXPECTED_VERSION" ] && ! $DOCTOR_POST_UPGRADE; then
        die "--expected-version requires --post-upgrade"
    fi
    if [ -n "$DOCTOR_EXPECTED_VERSION" ] && [[ ! "$DOCTOR_EXPECTED_VERSION" =~ ^[A-Za-z0-9._+-]{1,64}$ ]]; then
        die "Invalid value for doctor --expected-version: ${DOCTOR_EXPECTED_VERSION}"
    fi
}

# Counters and output helpers used only by doctor.
_DOCTOR_PASS=0
_DOCTOR_WARN=0
_DOCTOR_FAIL=0

_doctor_pass() {
    ((++_DOCTOR_PASS))
    ok "[PASS] $*"
}
_doctor_warn() {
    ((++_DOCTOR_WARN))
    warn "[WARN] $*"
}
_doctor_fail() {
    ((++_DOCTOR_FAIL))
    err "[FAIL] $*"
}

_doctor_check_engine() {
    if command -v "$CONTAINER_ENGINE" > /dev/null 2>&1; then
        _doctor_pass "Container engine found: $CONTAINER_ENGINE"
    else
        _doctor_fail "Container engine not found: install podman or docker"
        return
    fi

    if "$CONTAINER_ENGINE" info > /dev/null 2>&1; then
        _doctor_pass "Container engine daemon is reachable"
    else
        _doctor_fail "Container engine daemon is not reachable (podman machine start / systemctl start docker)"
    fi
}

_doctor_check_tools() {
    local tools=("$CONTAINER_ENGINE" "$COMPOSE" curl)
    if $USE_DEV_MODE; then
        tools+=(npm)
    fi
    if command -v ss > /dev/null 2>&1 || command -v netstat > /dev/null 2>&1; then
        _doctor_pass "Port-check tool available (ss/netstat)"
    else
        _doctor_warn "No ss or netstat found; port checks will be skipped"
    fi

    local missing=()
    for tool in "${tools[@]}"; do
        # Strip any subcommand (e.g. "podman compose" -> "podman").
        local bin="${tool%% *}"
        command -v "$bin" > /dev/null 2>&1 || missing+=("$bin")
    done

    if [ ${#missing[@]} -eq 0 ]; then
        _doctor_pass "Required tools found: ${tools[*]}"
    else
        _doctor_fail "Missing tools: ${missing[*]}"
    fi
}

_doctor_check_env_files() {
    if [ -f .env ] && [ -r .env ]; then
        _doctor_pass "Environment file found: .env"
    elif [ -f .env.development ] && [ -r .env.development ]; then
        _doctor_pass "Environment file found: .env.development"
    else
        _doctor_fail "No environment file found. Run: cp .env.example .env.development"
    fi
}

_doctor_check_secrets() {
    if [ "${APP_ENV:-development}" != "production" ]; then
        _doctor_pass "Production secret checks skipped (APP_ENV is not production)"
        return
    fi

    local jwt="${JWT_SECRET:-}"
    if [ -n "$jwt" ] && [[ "$jwt" != dev-jwt-secret-change-in-production* ]] && [ "${#jwt}" -ge 32 ]; then
        _doctor_pass "JWT_SECRET looks like a non-default value"
    else
        _doctor_fail "JWT_SECRET is unset or still using the development default"
    fi

    local session="${SESSION_SECRET:-}"
    if [ -n "$session" ] && [[ "$session" != dev-session-secret-change-in-production* ]]; then
        _doctor_pass "SESSION_SECRET looks like a non-default value"
    else
        _doctor_fail "SESSION_SECRET is unset or still using the development default"
    fi
}

_doctor_check_volume_path() {
    local path="${VOLUME_STORAGE_PATH:-}"
    if [ -z "$path" ]; then
        if [ "${APP_ENV:-development}" = "production" ]; then
            _doctor_fail "VOLUME_STORAGE_PATH is required in production"
        else
            _doctor_warn "VOLUME_STORAGE_PATH is not set (optional in development)"
        fi
        return
    fi

    if [ -d "$path" ]; then
        _doctor_pass "VOLUME_STORAGE_PATH exists: $path"
    else
        _doctor_fail "VOLUME_STORAGE_PATH does not exist: $path"
    fi
}

_doctor_check_ports() {
    if [ "${SKIP_PORT_CHECK:-false}" = "true" ]; then
        _doctor_pass "Port checks skipped (--skip-port-check)"
        return
    fi

    local ports=(8080 8443)
    if $USE_DEV_MODE; then
        ports+=(5173)
    fi
    if [ "${PGBOUNCER_ENABLED:-false}" = "true" ]; then
        ports+=(6432)
    fi
    if [ "${TRACING_ENABLED:-false}" = "true" ]; then
        ports+=(4317 4318)
    fi

    local busy=()
    for port in "${ports[@]}"; do
        if _preflight_port_in_use "$port"; then
            busy+=("$port")
        fi
    done

    if [ ${#busy[@]} -eq 0 ]; then
        _doctor_pass "Host ports are free: ${ports[*]}"
    else
        _doctor_fail "Port(s) already in use: ${busy[*]}"
    fi
}

_doctor_check_compose_files() {
    # Iterate by index so we can pair each -f with its value argument.
    local i
    for ((i = 0; i < ${#COMPOSE_ARGS[@]} - 1; i++)); do
        if [[ "${COMPOSE_ARGS[$i]}" == -f ]]; then
            local file="${COMPOSE_ARGS[$((i + 1))]}"
            if [ -f "$file" ]; then
                _doctor_pass "Compose file exists: $file"
            else
                _doctor_fail "Compose file missing: $file"
            fi
        fi
    done
}

_doctor_check_socket() {
    local sock="${DOCKER_SOCKET:-}"
    if [ -z "$sock" ]; then
        _doctor_warn "DOCKER_SOCKET is not set"
        return
    fi
    # -S specifically tests for a socket; a plain -e would mask a broken
    # setup where the path exists as a regular file but no listener is there.
    if [ -S "$sock" ]; then
        _doctor_pass "Container socket exists: $sock"
    elif [ -e "$sock" ]; then
        _doctor_fail "DOCKER_SOCKET exists but is not a socket: $sock"
    else
        _doctor_warn "Container socket not found: $sock"
    fi
}

_doctor_check_disk() {
    local threshold_kb=$((5 * 1024 * 1024)) # 5 GB
    local avail_kb
    if command -v df > /dev/null 2>&1; then
        avail_kb=$(df -k "$DIR" 2> /dev/null | awk 'NR==2 {print $4}')
        if [ -n "$avail_kb" ] && [ "$avail_kb" -lt "$threshold_kb" ]; then
            _doctor_warn "Low disk space on project filesystem: ${avail_kb}K free (< 5 GB)"
        else
            _doctor_pass "Project filesystem has sufficient free space"
        fi
    else
        _doctor_warn "Cannot check disk space: df not found"
    fi
}

# Recovery and registry preflight live in a sourced, read-only helper so
# this module stays focused on host checks.
# shellcheck source=../doctor/preflight.sh
source "$(dirname "${BASH_SOURCE[0]}")/../doctor/preflight.sh"

# Post-upgrade verification is read-only and bounded; default doctor behavior
# remains a stopped-stack-tolerant host preflight.
# shellcheck source=../doctor/post_upgrade.sh
source "$(dirname "${BASH_SOURCE[0]}")/../doctor/post_upgrade.sh"

cmd_doctor() {
    if $DOCTOR_POST_UPGRADE; then
        _doctor_post_upgrade
        return
    fi

    step "NukeLab environment check"

    _doctor_check_engine
    _doctor_check_tools
    _doctor_check_env_files
    _doctor_check_secrets
    _doctor_check_volume_path
    _doctor_check_ports
    _doctor_check_compose_files
    _doctor_check_socket
    _doctor_check_disk

    _doctor_load_schema
    _doctor_check_recovery_preflight
    _doctor_check_registry_preflight

    echo ""
    _doctor_info "Recovery preflight summary: config=${_DOCTOR_RECOVERY_STATE} journal=${_DOCTOR_RECOVERY_JOURNAL_STATE} volume_recovery=${_DOCTOR_VOLUME_RECOVERY_STATE}"
    _doctor_info "Registry preflight summary: policy=${_DOCTOR_REGISTRY_STATE} journal=${_DOCTOR_REGISTRY_JOURNAL_STATE}"
    if [ "$_DOCTOR_FAIL" -eq 0 ] && [ "$_DOCTOR_WARN" -eq 0 ]; then
        ok "All checks passed"
    elif [ "$_DOCTOR_FAIL" -eq 0 ]; then
        warn "$_DOCTOR_WARN warning(s); review above"
    else
        die "$_DOCTOR_FAIL failure(s); fix the issues above before continuing"
    fi
}
