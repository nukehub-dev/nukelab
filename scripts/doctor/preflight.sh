#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Read-only recovery and registry preflight helpers for `nukelabctl doctor`.
# Sourced by scripts/manage.d/doctor.sh after its output helpers are defined.

# ─── Recovery and registry preflight ──────────────────────────────────────
# Read-only only: SELECT queries, container path checks, and local image
# inspection. These checks never write SQL, pull images, start/stop
# containers, run migrations, or print executor ids, credentials, or file
# contents. A stopped stack is reported as unavailable, not as a failure.

_DOCTOR_DB_STATE="unknown"
_DOCTOR_RECOVERY_STATE="unknown"
_DOCTOR_RECOVERY_JOURNAL_STATE="unknown"
_DOCTOR_VOLUME_RECOVERY_STATE="unknown"
_DOCTOR_REGISTRY_STATE="unknown"
_DOCTOR_REGISTRY_JOURNAL_STATE="unknown"
_DOCTOR_WORKER_STALE="20"
_DOCTOR_LEGACY_DRAIN_CONFIRMED="false"

_DOCTOR_SCHEMA_WORKER_HB=false
_DOCTOR_SCHEMA_LAUNCH_COLUMNS=false
_DOCTOR_SCHEMA_BACKUP_COLUMNS=false
_DOCTOR_SCHEMA_RESTORE_COLUMNS=false
_DOCTOR_SCHEMA_ENVIRONMENT_REVISIONS=false
_DOCTOR_SCHEMA_PORTABLE_FINGERPRINT=false
_DOCTOR_SCHEMA_RUNTIME_IDENTITY=false
_DOCTOR_SCHEMA_TOOLCHAIN_IDENTITY=false
_DOCTOR_SCHEMA_REVISION_REVOKED=false
_DOCTOR_SCHEMA_REVISION_TEMPLATE_ID=false
_DOCTOR_SCHEMA_ENVIRONMENT_TEMPLATES=false
_DOCTOR_SCHEMA_TEMPLATE_IS_ACTIVE=false

_doctor_info() {
    info "[INFO] $*"
}

_doctor_is_positive_int() {
    [[ "$1" =~ ^[0-9]+$ ]] && [ "$1" -gt 0 ]
}

_doctor_normalize_bool() {
    case "${1,,}" in
        true | 1 | yes | on) echo "true" ;;
        false | 0 | no | off) echo "false" ;;
        *) return 1 ;;
    esac
}

# Run one read-only query through the stack's postgres service. Callers must
# check that the container is running first so a stopped stack stays quiet.
_doctor_psql() {
    local sql="$1"
    # COMPOSE may be a multi-word command ("docker compose"); the split is
    # intentional, matching the rest of the management scripts.
    # shellcheck disable=SC2086
    $COMPOSE "${COMPOSE_ARGS[@]}" exec -T postgres \
        psql -X -q -t -A -F '|' -v ON_ERROR_STOP=1 \
        -U "${DATABASE_USER:-nukelab}" -d "${DATABASE_NAME:-nukelab}" \
        -c "$sql" 2> /dev/null
}

_doctor_db_unavailable_label() {
    case "$_DOCTOR_DB_STATE" in
        stopped) echo "postgres container is not running (stack stopped)" ;;
        unreachable) echo "postgres is running but the read-only query failed" ;;
        *) echo "database is unavailable" ;;
    esac
}

_doctor_load_schema() {
    if ! _container_running nukelab-postgres; then
        _DOCTOR_DB_STATE="stopped"
        return 0
    fi

    local schema_sql="
SELECT 'worker_heartbeats', (to_regclass('public.worker_heartbeats') IS NOT NULL)::text
UNION ALL
SELECT 'launch_columns', (SELECT (count(*) = 2)::text FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'server_launch_operations' AND column_name IN ('executor_id', 'heartbeat_at'))
UNION ALL
SELECT 'backup_columns', (SELECT (count(*) = 2)::text FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'volume_backups' AND column_name IN ('executor_id', 'heartbeat_at'))
UNION ALL
SELECT 'restore_columns', (SELECT (count(*) = 2)::text FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'volume_restores' AND column_name IN ('executor_id', 'heartbeat_at'))
UNION ALL
SELECT 'environment_revisions', (to_regclass('public.environment_revisions') IS NOT NULL)::text
UNION ALL
SELECT 'portable_fingerprint', (SELECT (count(*) = 1)::text FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'environment_revisions' AND column_name = 'portable_fingerprint')
UNION ALL
SELECT 'runtime_identity', (SELECT (count(*) = 1)::text FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'environment_revisions' AND column_name = 'runtime_identity')
UNION ALL
SELECT 'toolchain_identity', (SELECT (count(*) = 1)::text FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'environment_revisions' AND column_name = 'toolchain_identity')
UNION ALL
SELECT 'revision_revoked', (SELECT (count(*) = 1)::text FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'environment_revisions' AND column_name = 'revoked')
UNION ALL
SELECT 'revision_template_id', (SELECT (count(*) = 1)::text FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'environment_revisions' AND column_name = 'template_id')
UNION ALL
SELECT 'environment_templates', (to_regclass('public.environment_templates') IS NOT NULL)::text
UNION ALL
SELECT 'template_is_active', (SELECT (count(*) = 1)::text FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'environment_templates' AND column_name = 'is_active')"

    local probe
    if ! probe=$(_doctor_psql "$schema_sql"); then
        _DOCTOR_DB_STATE="unreachable"
        return 0
    fi

    _DOCTOR_DB_STATE="reachable"
    local key value
    while IFS='|' read -r key value; do
        case "$key" in
            worker_heartbeats) _DOCTOR_SCHEMA_WORKER_HB="$value" ;;
            launch_columns) _DOCTOR_SCHEMA_LAUNCH_COLUMNS="$value" ;;
            backup_columns) _DOCTOR_SCHEMA_BACKUP_COLUMNS="$value" ;;
            restore_columns) _DOCTOR_SCHEMA_RESTORE_COLUMNS="$value" ;;
            environment_revisions) _DOCTOR_SCHEMA_ENVIRONMENT_REVISIONS="$value" ;;
            portable_fingerprint) _DOCTOR_SCHEMA_PORTABLE_FINGERPRINT="$value" ;;
            runtime_identity) _DOCTOR_SCHEMA_RUNTIME_IDENTITY="$value" ;;
            toolchain_identity) _DOCTOR_SCHEMA_TOOLCHAIN_IDENTITY="$value" ;;
            revision_revoked) _DOCTOR_SCHEMA_REVISION_REVOKED="$value" ;;
            revision_template_id) _DOCTOR_SCHEMA_REVISION_TEMPLATE_ID="$value" ;;
            environment_templates) _DOCTOR_SCHEMA_ENVIRONMENT_TEMPLATES="$value" ;;
            template_is_active) _DOCTOR_SCHEMA_TEMPLATE_IS_ACTIVE="$value" ;;
        esac
    done <<< "$probe"
}

_doctor_check_recovery_config() {
    local interval="${WORKER_HEARTBEAT_INTERVAL_SECONDS:-5}"
    local stale="${WORKER_HEARTBEAT_STALE_SECONDS:-20}"
    local operation_interval="${OPERATION_HEARTBEAT_INTERVAL_SECONDS:-10}"
    local operation_stale="${OPERATION_HEARTBEAT_STALE_SECONDS:-90}"
    local scan="${RECOVERY_SCAN_INTERVAL_SECONDS:-30}"
    local delay="${RECOVERY_INITIAL_DELAY_SECONDS:-60}"
    local prepared_grace="${RECOVERY_PREPARED_GRACE_SECONDS:-60}"
    local batch="${RECOVERY_SCAN_BATCH_SIZE:-200}"
    local stall="${RECOVERY_STALL_WARNING_SECONDS:-300}"
    local drain_raw="${RECOVERY_LEGACY_DRAIN_CONFIRMED:-false}"
    local invalid=false

    local -a settings=(
        "WORKER_HEARTBEAT_INTERVAL_SECONDS=$interval"
        "WORKER_HEARTBEAT_STALE_SECONDS=$stale"
        "OPERATION_HEARTBEAT_INTERVAL_SECONDS=$operation_interval"
        "OPERATION_HEARTBEAT_STALE_SECONDS=$operation_stale"
        "RECOVERY_SCAN_INTERVAL_SECONDS=$scan"
        "RECOVERY_INITIAL_DELAY_SECONDS=$delay"
        "RECOVERY_PREPARED_GRACE_SECONDS=$prepared_grace"
        "RECOVERY_SCAN_BATCH_SIZE=$batch"
        "RECOVERY_STALL_WARNING_SECONDS=$stall"
    )
    local item name value
    for item in "${settings[@]}"; do
        name="${item%%=*}"
        value="${item#*=}"
        if ! _doctor_is_positive_int "$value"; then
            _doctor_fail "Recovery configuration invalid: ${name} must be a positive integer (got: ${value})"
            invalid=true
        fi
    done

    if _doctor_is_positive_int "$interval" && _doctor_is_positive_int "$stale" && [ "$stale" -le "$interval" ]; then
        _doctor_fail "Recovery configuration invalid: WORKER_HEARTBEAT_STALE_SECONDS must be greater than WORKER_HEARTBEAT_INTERVAL_SECONDS"
        invalid=true
    fi
    if _doctor_is_positive_int "$operation_interval" && _doctor_is_positive_int "$operation_stale" && [ "$operation_stale" -le "$operation_interval" ]; then
        _doctor_fail "Recovery configuration invalid: OPERATION_HEARTBEAT_STALE_SECONDS must be greater than OPERATION_HEARTBEAT_INTERVAL_SECONDS"
        invalid=true
    fi

    local drain="false"
    if ! drain=$(_doctor_normalize_bool "$drain_raw"); then
        _doctor_fail "Recovery configuration invalid: RECOVERY_LEGACY_DRAIN_CONFIRMED must be true or false (got: ${drain_raw})"
        invalid=true
    fi

    if [ "$invalid" = "true" ]; then
        _DOCTOR_RECOVERY_STATE="invalid"
        return 0
    fi

    _DOCTOR_WORKER_STALE="$stale"
    _DOCTOR_LEGACY_DRAIN_CONFIRMED="$drain"
    _DOCTOR_RECOVERY_STATE="configured"
    _doctor_pass "Recovery scan configured: interval=${scan}s initial_delay=${delay}s batch=${batch} stall_warning=${stall}s legacy_drain=${drain}"
    _doctor_pass "Recovery timings: worker_heartbeat=${interval}s/${stale}s operation_heartbeat=${operation_interval}s/${operation_stale}s prepared_grace=${prepared_grace}s"
}

_doctor_check_volume_recovery() {
    local host_path="${VOLUME_BACKUP_HOST_PATH:-}"
    local container_path="${VOLUME_BACKUP_STORAGE_PATH:-}"
    local helper="${VOLUME_BACKUP_HELPER_IMAGE:-nukelab-volume-helper:latest}"
    local invalid=false
    local attention=false

    if [ -z "$host_path" ] && [ -z "$container_path" ]; then
        _DOCTOR_VOLUME_RECOVERY_STATE="disabled"
        _doctor_info "Volume recovery disabled: VOLUME_BACKUP_HOST_PATH and VOLUME_BACKUP_STORAGE_PATH are both unset"
        return 0
    fi

    if [ -z "$host_path" ] || [ -z "$container_path" ]; then
        _doctor_fail "Volume recovery is partially configured: set both VOLUME_BACKUP_HOST_PATH and VOLUME_BACKUP_STORAGE_PATH, or neither"
        _DOCTOR_VOLUME_RECOVERY_STATE="invalid"
        return 0
    fi

    local path
    for path in "$host_path" "$container_path"; do
        case "$path" in
            /*) ;;
            *)
                _doctor_fail "Volume recovery path must be absolute: ${path}"
                invalid=true
                ;;
        esac
        case "/${path}/" in
            */../*)
                _doctor_fail "Volume recovery path must not contain '..': ${path}"
                invalid=true
                ;;
        esac
    done
    if [ "$invalid" = "true" ]; then
        _DOCTOR_VOLUME_RECOVERY_STATE="invalid"
        return 0
    fi

    if [ -d "$host_path" ]; then
        _doctor_pass "Volume recovery host storage exists: ${host_path}"
    else
        _doctor_warn "Volume recovery host storage does not exist: ${host_path} (admission reports storage_unavailable)"
        attention=true
    fi

    # Mirror the helper's private-UID requirement using the backend container
    # view. This only reads directory metadata.
    if _container_running nukelab-backend; then
        local stat_line
        if stat_line=$(
            # shellcheck disable=SC2086
            $COMPOSE "${COMPOSE_ARGS[@]}" exec -T backend \
                stat -c '%u %g %a' "$container_path" 2> /dev/null
        ); then
            local uid gid mode
            read -r uid gid mode <<< "$stat_line"
            if [ "$uid" = "65532" ] && [ "$gid" = "65532" ] && [[ "$mode" =~ ^[0-7]{3,4}$ ]] && [ $((8#$mode & 077)) -eq 0 ]; then
                _doctor_pass "Volume recovery storage is private for helper UID 65532 inside backend"
            else
                _doctor_warn "Volume recovery storage inside backend is ${uid:-unknown}:${gid:-unknown} mode ${mode:-unknown}; helper UID 65532 needs a private 0700 directory (admission reports storage_unavailable)"
                attention=true
            fi
        else
            _doctor_warn "Volume recovery storage path is not accessible inside backend: ${container_path}"
            attention=true
        fi
    else
        _doctor_info "Volume recovery storage was not checked inside backend (container is not running)"
    fi

    if $CONTAINER_ENGINE image inspect "$helper" > /dev/null 2>&1; then
        _doctor_pass "Volume recovery helper image found locally: ${helper}"
        if [ "${APP_ENV:-development}" = "production" ] && [[ "$helper" != *"@sha256:"* ]]; then
            local last_component="${helper##*/}"
            if [[ "$last_component" != *:* || "${last_component##*:}" = "latest" ]]; then
                _doctor_warn "Volume recovery helper image uses a mutable tag in production: ${helper} (pin an immutable tag or digest)"
                attention=true
            fi
        fi
    else
        _doctor_warn "Volume recovery helper image not found locally: ${helper} (build or pull it before using volume recovery)"
        attention=true
    fi

    if [ "$attention" = "true" ]; then
        _DOCTOR_VOLUME_RECOVERY_STATE="attention"
    else
        _DOCTOR_VOLUME_RECOVERY_STATE="configured"
    fi
}

_doctor_check_recovery_journal() {
    if [ "$_DOCTOR_DB_STATE" != "reachable" ]; then
        _DOCTOR_RECOVERY_JOURNAL_STATE="unavailable"
        _doctor_info "Recovery journal checks unavailable: $(_doctor_db_unavailable_label)"
        return 0
    fi

    local missing=()
    [ "$_DOCTOR_SCHEMA_WORKER_HB" = "true" ] || missing+=("worker_heartbeats")
    [ "$_DOCTOR_SCHEMA_LAUNCH_COLUMNS" = "true" ] || missing+=("server_launch_operations.executor_id/heartbeat_at")
    [ "$_DOCTOR_SCHEMA_BACKUP_COLUMNS" = "true" ] || missing+=("volume_backups.executor_id/heartbeat_at")
    [ "$_DOCTOR_SCHEMA_RESTORE_COLUMNS" = "true" ] || missing+=("volume_restores.executor_id/heartbeat_at")
    if [ ${#missing[@]} -gt 0 ]; then
        _DOCTOR_RECOVERY_JOURNAL_STATE="schema-missing"
        _doctor_warn "Recovery journal schema is incomplete: missing ${missing[*]}; run ./nukelabctl db-migrate after a backup (read-only check; no migration was run)"
        return 0
    fi

    if [ "$_DOCTOR_RECOVERY_STATE" = "invalid" ]; then
        _doctor_info "Worker heartbeat freshness classification skipped: recovery configuration is invalid"
    else
        local heartbeat_row journal_complete=true
        if ! heartbeat_row=$(_doctor_psql "
SELECT count(*),
       count(*) FILTER (WHERE state = 'running' AND heartbeat_at >= (now() AT TIME ZONE 'UTC') - make_interval(secs => ${_DOCTOR_WORKER_STALE})),
       count(*) FILTER (WHERE state = 'running' AND heartbeat_at < (now() AT TIME ZONE 'UTC') - make_interval(secs => ${_DOCTOR_WORKER_STALE})),
       count(*) FILTER (WHERE state = 'stopped'),
       count(*) FILTER (WHERE state NOT IN ('running', 'stopped'))
FROM worker_heartbeats"); then
            _doctor_warn "Recovery journal heartbeat query failed; worker state is unavailable"
            journal_complete=false
        else
            local hb_total hb_fresh hb_stale hb_stopped hb_other
            IFS='|' read -r hb_total hb_fresh hb_stale hb_stopped hb_other <<< "$heartbeat_row"
            hb_total="${hb_total:-0}"
            hb_fresh="${hb_fresh:-0}"
            hb_stale="${hb_stale:-0}"
            hb_stopped="${hb_stopped:-0}"
            hb_other="${hb_other:-0}"

            _doctor_pass "Worker heartbeats: ${hb_total} total, ${hb_fresh} fresh (<${_DOCTOR_WORKER_STALE}s), ${hb_stale} stale, ${hb_stopped} stopped"
            if [ "$hb_other" -gt 0 ]; then
                _doctor_warn "${hb_other} worker heartbeat row(s) have an unrecognized state"
            fi

            local workers_running=false
            if _container_running nukelab-backend || _container_running nukelab-celery-worker; then
                workers_running=true
            fi
            if [ "$hb_total" -gt 0 ] && [ "$hb_fresh" -eq 0 ]; then
                _doctor_warn "No fresh worker heartbeats; registered executors may be stopped or unable to beat"
            elif [ "$hb_total" -eq 0 ] && $workers_running; then
                _doctor_warn "No worker heartbeat rows while backend/celery-worker is running; executor registration may be failing"
            fi
        fi
    fi

    local active_rows
    if ! active_rows=$(_doctor_psql "
SELECT 'launch',
       count(*) FILTER (WHERE state = 'prepared'),
       count(*) FILTER (WHERE state = 'executing'),
       count(*) FILTER (WHERE state = 'uncertain'),
       count(*) FILTER (WHERE executor_id IS NULL),
       count(*) FILTER (WHERE state <> 'prepared' AND executor_id IS NULL)
FROM server_launch_operations
WHERE state IN ('prepared', 'executing', 'uncertain')
UNION ALL
SELECT 'backup',
       count(*) FILTER (WHERE status = 'pending'),
       count(*) FILTER (WHERE status = 'in_progress'),
       count(*) FILTER (WHERE status = 'recovery_required'),
       count(*) FILTER (WHERE executor_id IS NULL),
       count(*) FILTER (WHERE status <> 'pending' AND executor_id IS NULL)
FROM volume_backups
WHERE status IN ('pending', 'in_progress', 'recovery_required')
UNION ALL
SELECT 'restore',
       count(*) FILTER (WHERE status = 'pending'),
       count(*) FILTER (WHERE status = 'in_progress'),
       count(*) FILTER (WHERE status = 'recovery_required'),
       count(*) FILTER (WHERE executor_id IS NULL),
       count(*) FILTER (WHERE status <> 'pending' AND executor_id IS NULL)
FROM volume_restores
WHERE status IN ('pending', 'in_progress', 'recovery_required')"); then
        _doctor_warn "Recovery journal row query failed; active operation counts are unavailable"
        _DOCTOR_RECOVERY_JOURNAL_STATE="partial"
        return 0
    fi

    local kind first second third without_executor legacy
    local attention_total=0 legacy_total=0
    while IFS='|' read -r kind first second third without_executor legacy; do
        [ -n "$kind" ] || continue
        first="${first:-0}"
        second="${second:-0}"
        third="${third:-0}"
        without_executor="${without_executor:-0}"
        legacy="${legacy:-0}"
        case "$kind" in
            launch)
                _doctor_pass "Launch operations: prepared=${first} executing=${second} uncertain=${third} without_executor=${without_executor} legacy_without_executor=${legacy}"
                attention_total=$((attention_total + third))
                ;;
            backup)
                _doctor_pass "Volume backups: pending=${first} in_progress=${second} recovery_required=${third} without_executor=${without_executor} legacy_without_executor=${legacy}"
                attention_total=$((attention_total + third))
                ;;
            restore)
                _doctor_pass "Volume restores: pending=${first} in_progress=${second} recovery_required=${third} without_executor=${without_executor} legacy_without_executor=${legacy}"
                attention_total=$((attention_total + third))
                ;;
            *)
                _doctor_warn "Recovery journal query returned an unexpected row kind"
                ;;
        esac
        legacy_total=$((legacy_total + legacy))
    done <<< "$active_rows"

    if [ "$attention_total" -gt 0 ]; then
        _doctor_warn "${attention_total} active operation(s) need attention (uncertain/recovery_required); inspect admin operations or volume recovery history"
    else
        _doctor_pass "No uncertain/recovery_required active operations"
    fi

    if [ "$legacy_total" -gt 0 ]; then
        if [ "$_DOCTOR_LEGACY_DRAIN_CONFIRMED" = "true" ]; then
            _doctor_pass "Legacy rows without executor_id: ${legacy_total}; RECOVERY_LEGACY_DRAIN_CONFIRMED=true (liveness is treated as stopped, terminal proof is still required)"
        else
            _doctor_warn "Legacy rows without executor_id: ${legacy_total}; RECOVERY_LEGACY_DRAIN_CONFIRMED is not true, so they remain ambiguous/recovery_required (complete the documented stop/drain before setting it)"
        fi
    else
        _doctor_pass "No legacy active rows without executor_id"
    fi

    if [ "${journal_complete:-true}" = "true" ]; then
        _DOCTOR_RECOVERY_JOURNAL_STATE="present"
    else
        _DOCTOR_RECOVERY_JOURNAL_STATE="partial"
    fi
}

_doctor_check_registry_config() {
    local policy="${REGISTRY_VERIFICATION_POLICY:-off}"
    local pull="${REGISTRY_PULL_POLICY:-on_demand}"
    local hosts="${REGISTRY_ALLOWED_HOSTS:-}"
    local invalid=false
    local entries=0

    case "$policy" in
        off | prefer | require) ;;
        *)
            _doctor_fail "Registry configuration invalid: REGISTRY_VERIFICATION_POLICY must be off, prefer, or require (got: ${policy})"
            invalid=true
            ;;
    esac
    case "$pull" in
        on_demand | preload_only) ;;
        *)
            _doctor_fail "Registry configuration invalid: REGISTRY_PULL_POLICY must be on_demand or preload_only (got: ${pull})"
            invalid=true
            ;;
    esac

    if [ -n "${hosts//[[:space:],]/}" ]; then
        local -a host_entries
        IFS=',' read -r -a host_entries <<< "$hosts"
        local entry trimmed
        for entry in "${host_entries[@]}"; do
            trimmed="${entry#"${entry%%[![:space:]]*}"}"
            trimmed="${trimmed%"${trimmed##*[![:space:]]}"}"
            [ -z "$trimmed" ] && continue
            entries=$((entries + 1))
            if [[ "$trimmed" == *"://"* || "$trimmed" == *"/"* || "$trimmed" == *" "* ]]; then
                _doctor_fail "Registry configuration invalid: REGISTRY_ALLOWED_HOSTS entry ${entries} is not a valid host"
                invalid=true
            fi
        done
    fi

    if [ "$invalid" = "true" ]; then
        _DOCTOR_REGISTRY_STATE="invalid"
        return 0
    fi

    _DOCTOR_REGISTRY_STATE="$policy"
    if [ "$entries" -eq 0 ]; then
        _doctor_pass "Registry verification policy=${policy} pull_policy=${pull} allowed_hosts=not set"
    else
        _doctor_pass "Registry verification policy=${policy} pull_policy=${pull} allowed_hosts=${entries} entry(s) configured"
    fi
}

_doctor_check_registry_credentials() {
    local host_file="${REGISTRY_CREDENTIALS_FILE_HOST:-}"

    if [ -z "$host_file" ] || [ "$host_file" = "/dev/null" ]; then
        _doctor_pass "Registry credentials: anonymous verification (REGISTRY_CREDENTIALS_FILE_HOST is unset or /dev/null)"
        return 0
    fi

    if [ ! -e "$host_file" ]; then
        _doctor_warn "Registry credentials file is configured but missing on the host: ${host_file} (verification falls back to anonymous)"
        return 0
    fi
    if [ ! -f "$host_file" ] || [ ! -r "$host_file" ]; then
        _doctor_warn "Registry credentials path is not a readable file on the host: ${host_file}"
        return 0
    fi
    _doctor_pass "Registry credentials file is present and readable on the host (contents not inspected)"

    local _container_path="/run/registry-credentials/config.json"
    local _configured_source
    _configured_source=$(readlink -f "$host_file" 2> /dev/null || echo "$host_file")
    local -a services=(backend celery-worker)
    local -a unreadable=() mismatched=()
    local checked=0 service
    for service in "${services[@]}"; do
        if _container_running "nukelab-${service}"; then
            checked=$((checked + 1))
            # shellcheck disable=SC2086
            if ! $COMPOSE "${COMPOSE_ARGS[@]}" exec -T "$service" test -r "$_container_path" > /dev/null 2>&1; then
                unreadable+=("$service")
                continue
            fi
            local mount_source
            # shellcheck disable=SC2086
            mount_source=$($CONTAINER_ENGINE inspect "nukelab-${service}" \
                --format '{{range .Mounts}}{{if eq .Destination "/run/registry-credentials/config.json"}}{{.Source}}{{end}}{{end}}' 2> /dev/null | tr -d '\n')
            if [ -z "$mount_source" ] || [ "$(readlink -f "$mount_source" 2> /dev/null || echo "$mount_source")" != "$_configured_source" ]; then
                # The running container was created with a different host
                # source; a restart is required after changing the env file.
                mismatched+=("$service")
            fi
        fi
    done

    if [ "$checked" -eq 0 ]; then
        _doctor_info "Registry credentials container readability not checked (backend/celery-worker are not running)"
    elif [ ${#unreadable[@]} -gt 0 ]; then
        _doctor_warn "Registry credentials file is not readable inside: ${unreadable[*]} (check REGISTRY_CREDENTIALS_FILE_HOST and the read-only mount)"
    elif [ ${#mismatched[@]} -gt 0 ]; then
        _doctor_warn "Registry credentials mount does not match REGISTRY_CREDENTIALS_FILE_HOST in: ${mismatched[*]} (restart the stack to apply the configured file)"
    else
        _doctor_pass "Registry credentials file is readable in backend and celery-worker (contents not inspected)"
    fi
}

_doctor_check_registry_journal() {
    if [ "$_DOCTOR_DB_STATE" != "reachable" ]; then
        _DOCTOR_REGISTRY_JOURNAL_STATE="unavailable"
        _doctor_info "Registry revision checks unavailable: $(_doctor_db_unavailable_label)"
        return 0
    fi

    local missing=()
    [ "$_DOCTOR_SCHEMA_ENVIRONMENT_REVISIONS" = "true" ] || missing+=("environment_revisions")
    [ "$_DOCTOR_SCHEMA_PORTABLE_FINGERPRINT" = "true" ] || missing+=("environment_revisions.portable_fingerprint")
    [ "$_DOCTOR_SCHEMA_RUNTIME_IDENTITY" = "true" ] || missing+=("environment_revisions.runtime_identity")
    [ "$_DOCTOR_SCHEMA_TOOLCHAIN_IDENTITY" = "true" ] || missing+=("environment_revisions.toolchain_identity")
    [ "$_DOCTOR_SCHEMA_REVISION_REVOKED" = "true" ] || missing+=("environment_revisions.revoked")
    [ "$_DOCTOR_SCHEMA_REVISION_TEMPLATE_ID" = "true" ] || missing+=("environment_revisions.template_id")
    [ "$_DOCTOR_SCHEMA_ENVIRONMENT_TEMPLATES" = "true" ] || missing+=("environment_templates")
    [ "$_DOCTOR_SCHEMA_TEMPLATE_IS_ACTIVE" = "true" ] || missing+=("environment_templates.is_active")
    if [ ${#missing[@]} -gt 0 ]; then
        _DOCTOR_REGISTRY_JOURNAL_STATE="schema-missing"
        _doctor_warn "Registry revision schema is incomplete: missing ${missing[*]}; run ./nukelabctl db-migrate after a backup (read-only check; no migration was run)"
        return 0
    fi

    local registry_row
    if ! registry_row=$(_doctor_psql "
SELECT
    (SELECT count(*) FROM environment_templates WHERE is_active IS TRUE),
    (SELECT count(*) FROM environment_revisions WHERE revoked = false),
    (SELECT count(*) FROM environment_revisions
      WHERE revoked = false
        AND COALESCE(runtime_identity->>'registry_verified', 'false') = 'true'
        AND (toolchain_identity IS NULL OR COALESCE(toolchain_identity->>'registry_verified', 'false') = 'true')),
    (SELECT count(*) FROM environment_revisions WHERE revoked = false AND portable_fingerprint IS NULL),
    (SELECT count(*) FROM environment_revisions
      WHERE revoked = false
        AND COALESCE(runtime_identity->>'registry_verified', 'false') = 'true'
        AND portable_fingerprint IS NULL),
    (SELECT count(*) FROM environment_revisions
      WHERE revoked = false
        AND COALESCE(runtime_identity->>'registry_verified', 'false') <> 'true'
        AND portable_fingerprint IS NOT NULL),
    (SELECT count(*) FROM environment_templates t
      WHERE t.is_active IS TRUE
        AND NOT EXISTS (SELECT 1 FROM environment_revisions r WHERE r.template_id = t.id AND r.revoked = false)),
    (SELECT count(*) FROM environment_templates t
      WHERE t.is_active IS TRUE
        AND NOT EXISTS (
          SELECT 1 FROM environment_revisions r
          WHERE r.template_id = t.id
            AND r.revoked = false
            AND COALESCE(r.runtime_identity->>'registry_verified', 'false') = 'true'
            AND (r.toolchain_identity IS NULL OR COALESCE(r.toolchain_identity->>'registry_verified', 'false') = 'true')
        ))"); then
        _DOCTOR_REGISTRY_JOURNAL_STATE="unavailable"
        _doctor_warn "Registry revision checks unavailable: the read-only database query failed"
        return 0
    fi

    local active_templates active_revisions verified portable_null verified_nonportable unverified_portable no_revision no_verified
    IFS='|' read -r active_templates active_revisions verified portable_null verified_nonportable unverified_portable no_revision no_verified <<< "$registry_row"
    active_templates="${active_templates:-0}"
    active_revisions="${active_revisions:-0}"
    verified="${verified:-0}"
    portable_null="${portable_null:-0}"
    verified_nonportable="${verified_nonportable:-0}"
    unverified_portable="${unverified_portable:-0}"
    no_revision="${no_revision:-0}"
    no_verified="${no_verified:-0}"
    local local_only=$((active_revisions - verified))

    _doctor_pass "Registry revisions: ${active_templates} active template(s), ${active_revisions} active revision(s), ${verified} registry-verified, ${local_only} local-only, ${portable_null} with portable_fingerprint NULL"

    if [ "$no_revision" -gt 0 ]; then
        _doctor_warn "${no_revision} active template(s) have no active revision; launch selection will fail until one is approved"
    fi
    if [ "$verified_nonportable" -gt 0 ]; then
        _doctor_warn "${verified_nonportable} registry-verified revision(s) have no portable fingerprint; their configuration is local-only by design (for example an unsupported volume declaration)"
    fi
    if [ "$unverified_portable" -gt 0 ]; then
        _doctor_warn "${unverified_portable} local-only revision(s) carry a portable fingerprint; revision metadata is inconsistent (re-verify the artifacts)"
    fi

    case "$_DOCTOR_REGISTRY_STATE" in
        off)
            if [ "$no_verified" -gt 0 ]; then
                _doctor_warn "REGISTRY_VERIFICATION_POLICY=off while ${no_verified} active template(s) have no registry-verified revision; consider prefer for new installations (intentionally air-gapped deployments may keep off)"
            fi
            if [ "$local_only" -gt 0 ]; then
                _doctor_info "${local_only} local-only revision(s) remain local-only by design under policy=off"
            fi
            ;;
        prefer)
            if [ "$local_only" -gt 0 ]; then
                _doctor_warn "${local_only} local-only revision(s) exist and were not promoted automatically; use the admin verify-artifacts action (no automatic retry in this release)"
            fi
            ;;
        require)
            if [ "$no_verified" -gt 0 ]; then
                _doctor_warn "${no_verified} active template(s) have no registry-verified revision; require fails closed when resolving a new verified artifact"
            fi
            if [ "$local_only" -gt 0 ]; then
                _doctor_warn "${local_only} local-only revision(s) exist under require; they are not portable and may not satisfy new verified resolution"
            fi
            ;;
    esac

    _DOCTOR_REGISTRY_JOURNAL_STATE="present"
}

_doctor_check_recovery_preflight() {
    step "Recovery preflight"
    _doctor_check_recovery_config
    _doctor_check_volume_recovery
    _doctor_check_recovery_journal
}

_doctor_check_registry_preflight() {
    step "Registry preflight"
    _doctor_check_registry_config
    _doctor_check_registry_credentials
    _doctor_check_registry_journal
}
