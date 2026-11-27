#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Read-only post-upgrade verification helpers for `nukelabctl doctor`.
# Sourced by scripts/manage.d/doctor.sh after its output and preflight helpers.
#
# These checks never write SQL, migrate, restart or create containers, pull
# images, or print credentials, payloads, mounts, owner identifiers, or raw
# errors. Required checks fail the mode; warnings require review but do not.

_DOCTOR_POST_STACK_STATE="unknown"
_DOCTOR_POST_API_STATE="unknown"
_DOCTOR_POST_IMAGE_STATE="unknown"
_DOCTOR_POST_SCHEMA_STATE="unknown"
_DOCTOR_POST_WORKER_STATE="unknown"
_DOCTOR_POST_BEAT_STATE="unknown"
_DOCTOR_POST_RECOVERY_STATE="unknown"
_DOCTOR_POST_BATCH_STATE="unknown"
_DOCTOR_POST_EXPECTED_VERSION=""
_DOCTOR_POST_OBSERVED_VERSION=""

_doctor_post_age_label() {
    if [[ "${1:-}" =~ ^[0-9]+$ ]]; then
        echo "${1}s"
    else
        echo "unknown"
    fi
}

_doctor_post_short_image_id() {
    local digest="${1#sha256:}"
    echo "${digest:0:12}"
}

_doctor_post_image_tag() {
    local ref="$1"
    case "$ref" in
        *"@sha256:"*) echo "digest" ;;
        *)
            local last="${ref##*/}"
            if [[ "$last" == *:* ]]; then
                echo "${last##*:}"
            else
                echo "none"
            fi
            ;;
    esac
}

# Derive the release the operator expects to be deployed. An explicit
# --expected-version wins; otherwise use the resolved NUKELAB_VERSION, then the
# VERSION file or git tag helpers. A leading "v" is normalized away.
_doctor_post_resolve_expected_version() {
    local version="${DOCTOR_EXPECTED_VERSION:-}"
    if [ -z "$version" ]; then
        version="${NUKELAB_VERSION:-}"
    fi
    if [ -z "$version" ]; then
        version="$(_nukelab_version)"
    fi
    echo "${version#v}"
}

_doctor_post_check_engine() {
    if ! command -v "$CONTAINER_ENGINE" > /dev/null 2>&1; then
        _doctor_fail "Container engine not found: ${CONTAINER_ENGINE}"
        return
    fi
    if ! _doctor_timeout 10 "$CONTAINER_ENGINE" info > /dev/null 2>&1; then
        _doctor_fail "Container engine daemon is not reachable: ${CONTAINER_ENGINE}"
        return
    fi
    _doctor_pass "Container engine reachable: ${CONTAINER_ENGINE}"

    if ! command -v curl > /dev/null 2>&1; then
        _doctor_fail "curl is required for API verification but was not found"
    fi
    if ! command -v timeout > /dev/null 2>&1; then
        _doctor_warn "timeout not found; probes use tool-native timeouts only"
    fi
}

_doctor_post_check_stack() {
    local -a expected=(postgres redis backend celery-worker celery-beat)
    if ! $USE_DEV_MODE; then
        expected+=(traefik frontend)
    fi
    if [ "${PGBOUNCER_ENABLED:-false}" = "true" ] || _has_overlay "compose.pgbouncer.yml"; then
        expected+=(pgbouncer)
    fi

    local -a running=() missing=()
    local service
    for service in "${expected[@]}"; do
        if _container_running "nukelab-${service}"; then
            running+=("$service")
        else
            missing+=("$service")
        fi
    done

    if [ ${#missing[@]} -eq 0 ]; then
        _DOCTOR_POST_STACK_STATE="pass"
        _doctor_pass "Required services running: ${running[*]}"
    else
        _DOCTOR_POST_STACK_STATE="fail"
        _doctor_fail "Required service container(s) not running: ${missing[*]}; run ./nukelabctl status and ./nukelabctl logs <service>"
    fi
}

# Check the public health and release-status endpoints through the local edge.
# /api/health/status is unauthenticated and only exposes the release version.
_doctor_post_check_api() {
    local base="http://127.0.0.1:8080"
    local health_tmp status_tmp
    local health_code="" status_code="" curl_rc=0
    local observed=""

    if ! command -v curl > /dev/null 2>&1; then
        _DOCTOR_POST_API_STATE="unavailable"
        return
    fi
    if ! health_tmp=$(mktemp 2> /dev/null); then
        _DOCTOR_POST_API_STATE="unavailable"
        _doctor_fail "API health could not be verified: unable to create a temporary file"
        return
    fi
    if ! status_tmp=$(mktemp 2> /dev/null); then
        rm -f "$health_tmp"
        _DOCTOR_POST_API_STATE="unavailable"
        _doctor_fail "API release version could not be verified: unable to create a temporary file"
        return
    fi

    health_code=$(_doctor_timeout 8 curl -sS --connect-timeout 3 --max-time 5 \
        -o "$health_tmp" -w '%{http_code}' "${base}/api/system/health" 2> /dev/null) || curl_rc=$?
    if [ "$curl_rc" -ne 0 ] || [ "$health_code" != "200" ]; then
        _DOCTOR_POST_API_STATE="unreachable"
        _doctor_fail "API health endpoint is not reachable at ${base}/api/system/health (curl=${curl_rc} http=${health_code:-none}); check ./nukelabctl logs backend and ./nukelabctl logs traefik"
        rm -f "$health_tmp" "$status_tmp"
        return
    fi
    if ! grep -q '"status"[[:space:]]*:[[:space:]]*"healthy"' "$health_tmp"; then
        _DOCTOR_POST_API_STATE="degraded"
        _doctor_fail "API health endpoint returned HTTP 200 without a healthy status (maintenance or degraded mode); finish maintenance before resuming traffic"
        rm -f "$health_tmp" "$status_tmp"
        return
    fi
    _doctor_pass "API basic health: ${base}/api/system/health returned healthy"

    curl_rc=0
    status_code=$(_doctor_timeout 8 curl -sS --connect-timeout 3 --max-time 5 \
        -o "$status_tmp" -w '%{http_code}' "${base}/api/health/status" 2> /dev/null) || curl_rc=$?
    if [ "$curl_rc" -ne 0 ] || [ "$status_code" != "200" ]; then
        _DOCTOR_POST_API_STATE="unreachable"
        _doctor_fail "API release status endpoint is not reachable at ${base}/api/health/status (curl=${curl_rc} http=${status_code:-none}); expected version ${_DOCTOR_POST_EXPECTED_VERSION}"
        rm -f "$health_tmp" "$status_tmp"
        return
    fi

    observed=$(tr -d '\n' < "$status_tmp" | sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)
    observed="${observed#v}"
    rm -f "$health_tmp" "$status_tmp"

    if [[ ! "$observed" =~ ^[A-Za-z0-9._+-]{1,64}$ ]]; then
        _DOCTOR_POST_API_STATE="unreadable"
        _doctor_fail "API responded but did not report a readable release version; expected ${_DOCTOR_POST_EXPECTED_VERSION}, observed unavailable"
        return
    fi

    _DOCTOR_POST_OBSERVED_VERSION="$observed"
    if [ "$observed" = "$_DOCTOR_POST_EXPECTED_VERSION" ]; then
        _DOCTOR_POST_API_STATE="pass"
        _doctor_pass "API release version matches expected: expected=${_DOCTOR_POST_EXPECTED_VERSION} observed=${observed}"
    else
        _DOCTOR_POST_API_STATE="mismatch"
        _doctor_fail "API release version mismatch: expected=${_DOCTOR_POST_EXPECTED_VERSION} observed=${observed}; the running API is not the pinned release"
    fi

    if [ "$_DOCTOR_POST_EXPECTED_VERSION" = "0.0.0-dev" ]; then
        _doctor_warn "Expected release version is the development fallback 0.0.0-dev; this deployment is not pinned to a release"
    fi
}

# Compare running service image identity with the expected pinned tag and with
# each other. Config.Image is a registry reference; no credentials are exposed.
_doctor_post_check_images() {
    local -a services=(backend celery-worker celery-beat)
    if ! $USE_DEV_MODE; then
        services+=(frontend)
    fi

    local -A refs=()
    local -A ids=()
    local -a unavailable=()
    local service line ref image_id
    for service in "${services[@]}"; do
        if ! _container_running "nukelab-${service}"; then
            unavailable+=("$service")
            continue
        fi
        if line=$(_doctor_timeout 10 "$CONTAINER_ENGINE" inspect "nukelab-${service}" \
            --format '{{.Config.Image}}|{{.Image}}' 2> /dev/null | tr -d '\n'); then
            if [ -n "$line" ]; then
                IFS='|' read -r ref image_id <<< "$line"
                refs["$service"]="$ref"
                ids["$service"]="$image_id"
            fi
        fi
        if [ -z "${refs[$service]:-}" ]; then
            unavailable+=("$service")
        fi
    done

    if [ ${#unavailable[@]} -gt 0 ]; then
        _DOCTOR_POST_IMAGE_STATE="unavailable"
        _doctor_fail "Running image identity is unavailable for: ${unavailable[*]}; start the missing services before verifying images"
    fi

    local backend_id="${ids[backend]:-}"
    local worker_id="${ids["celery-worker"]:-}"
    local beat_id="${ids["celery-beat"]:-}"
    if [ -n "$backend_id" ] && [ -n "$worker_id" ] && [ -n "$beat_id" ]; then
        if [ "$backend_id" = "$worker_id" ] && [ "$backend_id" = "$beat_id" ]; then
            _doctor_pass "Backend, Celery worker and Beat run the same image: backend=${refs[backend]} celery-worker=${refs["celery-worker"]} celery-beat=${refs["celery-beat"]}"
        else
            _DOCTOR_POST_IMAGE_STATE="mismatch"
            _doctor_fail "Backend service images differ: backend=${refs[backend]} (id=$(_doctor_post_short_image_id "$backend_id")) celery-worker=${refs["celery-worker"]} (id=$(_doctor_post_short_image_id "$worker_id")) celery-beat=${refs["celery-beat"]} (id=$(_doctor_post_short_image_id "$beat_id")); recreate them from one release"
        fi
    fi

    local expected_tag="${NUKELAB_IMAGE_TAG:-}"
    local pinned=false
    if [ -n "$expected_tag" ] && [ "$expected_tag" != "latest" ]; then
        pinned=true
    fi

    if ! $pinned; then
        if [ "$_DOCTOR_POST_IMAGE_STATE" = "unknown" ]; then
            _DOCTOR_POST_IMAGE_STATE="unpinned"
        fi
        _doctor_info "Running service image references: backend=${refs[backend]:-unavailable} celery-worker=${refs["celery-worker"]:-unavailable} celery-beat=${refs["celery-beat"]:-unavailable} frontend=${refs[frontend]:-unavailable}"
        _doctor_warn "Image tag is not pinned (NUKELAB_IMAGE_TAG=${expected_tag:-unset}); pin a release to verify exact image identity"
        return
    fi

    local -a mismatches=()
    local observed_tag=""
    for service in backend celery-worker celery-beat; do
        if [ -z "${refs[$service]:-}" ]; then
            mismatches+=("${service}=unavailable")
            continue
        fi
        observed_tag="$(_doctor_post_image_tag "${refs[$service]}")"
        if [ "$observed_tag" != "$expected_tag" ]; then
            mismatches+=("${service}=${refs[$service]} (tag=${observed_tag})")
        fi
    done
    if ! $USE_DEV_MODE; then
        if [ -z "${refs[frontend]:-}" ]; then
            mismatches+=("frontend=unavailable")
        else
            observed_tag="$(_doctor_post_image_tag "${refs[frontend]}")"
            if [ "$observed_tag" != "$expected_tag" ]; then
                mismatches+=("frontend=${refs[frontend]} (tag=${observed_tag})")
            fi
        fi
    fi

    if [ ${#mismatches[@]} -eq 0 ]; then
        _DOCTOR_POST_IMAGE_STATE="pass"
        _doctor_pass "Running service image tags match the pinned release: expected=${expected_tag} observed=backend=${refs[backend]},celery-worker=${refs["celery-worker"]},celery-beat=${refs["celery-beat"]}${refs[frontend]:+,frontend=${refs[frontend]}}"
    else
        _DOCTOR_POST_IMAGE_STATE="mismatch"
        _doctor_fail "Running service image tags do not match the pinned release ${expected_tag}: expected=${expected_tag} observed=${mismatches[*]}; run ./nukelabctl update and recreate the stack"
    fi

    if [ "$expected_tag" != "$_DOCTOR_POST_EXPECTED_VERSION" ]; then
        _doctor_warn "Pinned image tag (${expected_tag}) differs from the expected release version (${_DOCTOR_POST_EXPECTED_VERSION}); API version is verified against the latter"
    fi
}

_doctor_post_check_schema() {
    if [ "$_DOCTOR_DB_STATE" != "reachable" ]; then
        _DOCTOR_POST_SCHEMA_STATE="unavailable"
        _doctor_fail "Database schema compatibility could not be verified: $(_doctor_db_unavailable_label)"
        return
    fi

    local table_exists
    if ! table_exists=$(_doctor_psql "SELECT to_regclass('public.alembic_version') IS NOT NULL"); then
        _DOCTOR_POST_SCHEMA_STATE="unavailable"
        _doctor_fail "Database schema compatibility could not be verified: the read-only alembic_version probe failed"
        return
    fi
    if [ "$table_exists" != "t" ]; then
        _DOCTOR_POST_SCHEMA_STATE="missing"
        _doctor_fail "alembic_version table is missing; run ./nukelabctl db-migrate after taking a snapshot"
        return
    fi

    local current_rows
    if ! current_rows=$(_doctor_psql "SELECT version_num FROM alembic_version"); then
        _DOCTOR_POST_SCHEMA_STATE="unavailable"
        _doctor_fail "Database schema compatibility could not be verified: the alembic_version query failed"
        return
    fi

    local current_list=""
    local current_count=0
    local revision
    while IFS= read -r revision; do
        revision="${revision//[[:space:]]/}"
        [ -n "$revision" ] || continue
        current_list="${current_list:+${current_list},}${revision}"
        current_count=$((current_count + 1))
    done <<< "$current_rows"

    if [ "$current_count" -eq 0 ]; then
        _DOCTOR_POST_SCHEMA_STATE="missing"
        _doctor_fail "alembic_version is empty; run ./nukelabctl db-migrate after taking a snapshot"
        return
    fi
    if [ "$current_count" -gt 1 ]; then
        _DOCTOR_POST_SCHEMA_STATE="multiple"
        _doctor_fail "alembic_version contains multiple revisions (${current_list}); resolve the migration branches before resuming traffic"
        return
    fi

    local head_out
    # shellcheck disable=SC2086
    if ! head_out=$(_doctor_timeout 20 $COMPOSE "${COMPOSE_ARGS[@]}" exec -T -e PYTHONDONTWRITEBYTECODE=1 backend alembic heads 2> /dev/null); then
        _DOCTOR_POST_SCHEMA_STATE="unavailable"
        _doctor_fail "Backend Alembic head could not be read; expected=${current_list} observed=unavailable (check ./nukelabctl logs backend)"
        return
    fi

    local -a head_revisions=()
    local line
    while IFS= read -r line; do
        case "$line" in
            *"(head)"*)
                revision="${line%%[[:space:]]*}"
                [ -n "$revision" ] && head_revisions+=("$revision")
                ;;
        esac
    done <<< "$head_out"

    if [ ${#head_revisions[@]} -eq 0 ]; then
        _DOCTOR_POST_SCHEMA_STATE="unavailable"
        _doctor_fail "Backend image did not report an Alembic head; expected=${current_list} observed=unavailable"
        return
    fi
    if [ ${#head_revisions[@]} -gt 1 ]; then
        _DOCTOR_POST_SCHEMA_STATE="multiple"
        _doctor_fail "Backend image reports multiple Alembic heads (${head_revisions[*]}); expected=one head observed=${#head_revisions[@]} heads"
        return
    fi

    local expected_head="${head_revisions[0]}"
    if [ "$current_list" = "$expected_head" ]; then
        _DOCTOR_POST_SCHEMA_STATE="pass"
        _doctor_pass "Database schema matches the backend image head: expected=${expected_head} observed=${current_list}"
        return
    fi

    if _doctor_timeout 20 $COMPOSE "${COMPOSE_ARGS[@]}" exec -T -e PYTHONDONTWRITEBYTECODE=1 backend alembic show "$current_list" > /dev/null 2>&1; then
        _DOCTOR_POST_SCHEMA_STATE="behind"
        _doctor_fail "Database schema is behind the backend image: expected=${expected_head} observed=${current_list}; run ./nukelabctl db-migrate (it takes a pre-migration snapshot)"
    else
        _DOCTOR_POST_SCHEMA_STATE="unknown"
        _doctor_fail "Database schema revision is unknown to the running backend image (newer or divergent): expected=${expected_head} observed=${current_list}; restore the marked snapshot or deploy the matching release"
    fi
}

_doctor_post_check_worker() {
    if [ "$_DOCTOR_DB_STATE" != "reachable" ]; then
        _DOCTOR_POST_WORKER_STATE="unavailable"
        _doctor_fail "Celery worker heartbeat could not be verified: $(_doctor_db_unavailable_label)"
        return
    fi
    if [ "$_DOCTOR_SCHEMA_WORKER_HB" != "true" ]; then
        _DOCTOR_POST_WORKER_STATE="missing"
        _doctor_fail "worker_heartbeats table is missing; run ./nukelabctl db-migrate after taking a snapshot"
        return
    fi
    if ! _container_running nukelab-celery-worker; then
        _DOCTOR_POST_WORKER_STATE="missing"
        _doctor_fail "celery-worker container is not running; heartbeat freshness cannot be verified"
        return
    fi

    local stale="${_DOCTOR_WORKER_STALE:-20}"
    local row
    if ! row=$(_doctor_psql "
SELECT
    count(*) FILTER (WHERE state = 'running' AND single_process_container AND heartbeat_at >= (now() AT TIME ZONE 'UTC') - make_interval(secs => ${stale})),
    count(*) FILTER (WHERE state = 'running' AND single_process_container AND heartbeat_at < (now() AT TIME ZONE 'UTC') - make_interval(secs => ${stale})),
    COALESCE(floor(EXTRACT(EPOCH FROM (now() AT TIME ZONE 'UTC') - max(heartbeat_at) FILTER (WHERE single_process_container))), -1)::bigint
FROM worker_heartbeats"); then
        _DOCTOR_POST_WORKER_STATE="unavailable"
        _doctor_fail "Celery worker heartbeat query failed; expected=fresh heartbeat within ${stale}s observed=unavailable"
        return
    fi

    local fresh=0 stale_count=0 age=-1
    IFS='|' read -r fresh stale_count age <<< "$row"
    fresh="${fresh:-0}"
    stale_count="${stale_count:-0}"
    age="${age:--1}"

    if [ "$fresh" -gt 0 ]; then
        _DOCTOR_POST_WORKER_STATE="pass"
        _doctor_pass "Celery worker heartbeat is fresh: fresh=${fresh} stale=${stale_count} last=$(_doctor_post_age_label "$age") (threshold=${stale}s)"
        if [ "$stale_count" -gt 0 ]; then
            _doctor_warn "${stale_count} stale Celery worker heartbeat row(s) remain; inspect only if they are unexpected"
        fi
    else
        _DOCTOR_POST_WORKER_STATE="stale"
        _doctor_fail "No fresh Celery worker heartbeat: fresh=0 stale=${stale_count} last=$(_doctor_post_age_label "$age") (threshold=${stale}s); check ./nukelabctl logs celery-worker"
    fi
}

_doctor_post_check_beat() {
    if ! _container_running nukelab-celery-beat; then
        _DOCTOR_POST_BEAT_STATE="missing"
        _doctor_fail "Celery Beat container is not running; scheduled recovery scans will not run"
        return
    fi
    _doctor_pass "Celery Beat container is running (Beat does not register a worker heartbeat; presence is checked by container state and recovery-scan freshness)"

    if [ "$_DOCTOR_DB_STATE" != "reachable" ]; then
        _DOCTOR_POST_BEAT_STATE="unavailable"
        _doctor_warn "Recovery-scan freshness is unavailable: $(_doctor_db_unavailable_label)"
        return
    fi

    local settings_exists
    if ! settings_exists=$(_doctor_psql "SELECT to_regclass('public.system_settings') IS NOT NULL"); then
        _DOCTOR_POST_BEAT_STATE="unavailable"
        _doctor_warn "Recovery-scan freshness is unavailable: the read-only system_settings probe failed"
        return
    fi
    if [ "$settings_exists" != "t" ]; then
        _DOCTOR_POST_BEAT_STATE="unavailable"
        _doctor_warn "Recovery-scan freshness is unavailable: system_settings table is missing"
        return
    fi

    local scan_age
    if ! scan_age=$(_doctor_psql "
SELECT COALESCE((
    SELECT floor(EXTRACT(EPOCH FROM (now() AT TIME ZONE 'UTC')) - (value::jsonb->>'last_success_at')::double precision)
    FROM system_settings
    WHERE key = 'recovery_scan_state'
      AND value ~ '^[[:space:]]*\{'
      AND (value::jsonb ? 'last_success_at')
    LIMIT 1
), -1)::bigint"); then
        _DOCTOR_POST_BEAT_STATE="unavailable"
        _doctor_warn "Recovery-scan freshness is unavailable: the read-only recovery_scan_state query failed"
        return
    fi

    scan_age="${scan_age:--1}"
    if [ "$scan_age" -lt 0 ]; then
        _DOCTOR_POST_BEAT_STATE="no-scan"
        _doctor_warn "No recovery scan has been recorded yet; Beat may still be in its initial delay or Prometheus metrics are disabled (recovery-scan freshness is advisory, Beat presence is checked by container state)"
        return
    fi

    local scan_interval="${RECOVERY_SCAN_INTERVAL_SECONDS:-30}"
    local scan_delay="${RECOVERY_INITIAL_DELAY_SECONDS:-60}"
    if [[ ! "$scan_interval" =~ ^[1-9][0-9]*$ ]]; then
        scan_interval=30
    fi
    if [[ ! "$scan_delay" =~ ^[1-9][0-9]*$ ]]; then
        scan_delay=60
    fi
    local stale_after=$((scan_interval * 2 + scan_delay + 60))
    if [ "$scan_age" -le "$stale_after" ]; then
        _DOCTOR_POST_BEAT_STATE="pass"
        _doctor_pass "Recovery scan is fresh: last_success=$(_doctor_post_age_label "$scan_age") threshold=${stale_after}s"
    else
        _DOCTOR_POST_BEAT_STATE="stale"
        _doctor_warn "Recovery scan is stale: last_success=$(_doctor_post_age_label "$scan_age") exceeds ${stale_after}s (interval=${scan_interval}s initial_delay=${scan_delay}s); check ./nukelabctl logs celery-beat and ./nukelabctl logs celery-worker"
    fi
}

_doctor_post_check_recovery() {
    if [ "$_DOCTOR_DB_STATE" != "reachable" ]; then
        _DOCTOR_POST_RECOVERY_STATE="unavailable"
        _doctor_fail "Unresolved recovery rows could not be verified: $(_doctor_db_unavailable_label)"
        return
    fi

    local -a missing=()
    [ "$_DOCTOR_SCHEMA_LAUNCH_COLUMNS" = "true" ] || missing+=("server_launch_operations.executor_id/heartbeat_at")
    [ "$_DOCTOR_SCHEMA_BACKUP_COLUMNS" = "true" ] || missing+=("volume_backups.executor_id/heartbeat_at")
    [ "$_DOCTOR_SCHEMA_RESTORE_COLUMNS" = "true" ] || missing+=("volume_restores.executor_id/heartbeat_at")
    if [ ${#missing[@]} -gt 0 ]; then
        _DOCTOR_POST_RECOVERY_STATE="missing"
        _doctor_fail "Recovery journal schema is incomplete: missing ${missing[*]}; run ./nukelabctl db-migrate after taking a snapshot"
        return
    fi

    local rows
    if ! rows=$(_doctor_psql "
SELECT 'launch', count(*), COALESCE(floor(EXTRACT(EPOCH FROM (now() AT TIME ZONE 'UTC') - min(created_at))), -1)::bigint
FROM server_launch_operations
WHERE state = 'uncertain'
UNION ALL
SELECT 'backup', count(*), COALESCE(floor(EXTRACT(EPOCH FROM (now() AT TIME ZONE 'UTC') - min(created_at))), -1)::bigint
FROM volume_backups
WHERE status = 'recovery_required'
UNION ALL
SELECT 'restore', count(*), COALESCE(floor(EXTRACT(EPOCH FROM (now() AT TIME ZONE 'UTC') - min(created_at))), -1)::bigint
FROM volume_restores
WHERE status = 'recovery_required'"); then
        _DOCTOR_POST_RECOVERY_STATE="unavailable"
        _doctor_fail "Unresolved recovery-row query failed; expected=0 rows observed=unavailable"
        return
    fi

    local kind count age details="" total=0
    while IFS='|' read -r kind count age; do
        [ -n "$kind" ] || continue
        count="${count:-0}"
        age="${age:--1}"
        if [ "$count" -gt 0 ]; then
            details="${details}${details:+, }${kind}=${count} (oldest=$(_doctor_post_age_label "$age"))"
            total=$((total + count))
        fi
    done <<< "$rows"

    if [ "$total" -gt 0 ]; then
        _DOCTOR_POST_RECOVERY_STATE="attention"
        _doctor_fail "Unresolved recovery rows need operator attention before resuming traffic: ${details}; inspect the admin operations page and ./nukelabctl logs celery-worker"
    else
        _DOCTOR_POST_RECOVERY_STATE="pass"
        _doctor_pass "No unresolved launch, backup or restore recovery rows"
    fi

    local active
    if active=$(_doctor_psql "
SELECT
    (SELECT count(*) FROM server_launch_operations WHERE state IN ('prepared', 'executing')),
    (SELECT count(*) FROM volume_backups WHERE status IN ('pending', 'in_progress')),
    (SELECT count(*) FROM volume_restores WHERE status IN ('pending', 'in_progress'))"); then
        local launches backups restores
        IFS='|' read -r launches backups restores <<< "$active"
        _doctor_info "Active recovery rows (not a failure): launch=${launches:-0} backup=${backups:-0} restore=${restores:-0}"
    fi
}

_doctor_post_check_batch_jobs() {
    if [ "$_DOCTOR_DB_STATE" != "reachable" ]; then
        _DOCTOR_POST_BATCH_STATE="unavailable"
        _doctor_info "Batch-job freshness unavailable: $(_doctor_db_unavailable_label)"
        return
    fi

    local table_exists
    if ! table_exists=$(_doctor_psql "SELECT to_regclass('public.batch_jobs') IS NOT NULL"); then
        _DOCTOR_POST_BATCH_STATE="unavailable"
        _doctor_info "Batch-job freshness unavailable: the read-only batch_jobs probe failed"
        return
    fi
    if [ "$table_exists" != "t" ]; then
        _DOCTOR_POST_BATCH_STATE="not-installed"
        _doctor_info "Batch jobs are not installed on this deployment (no batch_jobs table); skipped"
        return
    fi

    local columns
    if ! columns=$(_doctor_psql "
SELECT count(*)
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'batch_jobs'
  AND column_name IN ('state', 'created_at')"); then
        _DOCTOR_POST_BATCH_STATE="unavailable"
        _doctor_warn "Batch-job freshness is unavailable: the read-only column probe failed"
        return
    fi
    if [ "${columns:-0}" != "2" ]; then
        _DOCTOR_POST_BATCH_STATE="unavailable"
        _doctor_warn "batch_jobs exists but does not expose the expected state/created_at columns; freshness probe skipped (not a failure)"
        return
    fi

    local rows
    if ! rows=$(_doctor_psql "
SELECT
    count(*) FILTER (WHERE state IN ('queued', 'starting', 'running', 'cancelling')),
    count(*) FILTER (WHERE state = 'recovery_required'),
    count(*) FILTER (WHERE state = 'queued'),
    COALESCE(floor(EXTRACT(EPOCH FROM (now() AT TIME ZONE 'UTC') - min(created_at) FILTER (WHERE state = 'queued'))), -1)::bigint,
    COALESCE(floor(EXTRACT(EPOCH FROM (now() AT TIME ZONE 'UTC') - min(created_at) FILTER (WHERE state IN ('queued', 'starting', 'running', 'cancelling')))), -1)::bigint
FROM batch_jobs"); then
        _DOCTOR_POST_BATCH_STATE="unavailable"
        _doctor_warn "Batch-job freshness is unavailable: the read-only row probe failed"
        return
    fi

    local active=0 recovery=0 queued=0 queued_age=-1 active_age=-1
    IFS='|' read -r active recovery queued queued_age active_age <<< "$rows"
    active="${active:-0}"
    recovery="${recovery:-0}"
    queued="${queued:-0}"
    queued_age="${queued_age:--1}"
    active_age="${active_age:--1}"

    local heartbeat_columns=0
    local batch_attention=false
    if heartbeat_columns=$(_doctor_psql "
SELECT count(*)
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'batch_jobs'
  AND column_name = 'heartbeat_at'"); then
        if [ "$heartbeat_columns" = "1" ]; then
            local operation_stale="${OPERATION_HEARTBEAT_STALE_SECONDS:-90}"
            if [[ ! "$operation_stale" =~ ^[1-9][0-9]*$ ]]; then
                operation_stale=90
            fi
            local stale_running
            if stale_running=$(_doctor_psql "
SELECT count(*)
FROM batch_jobs
WHERE state = 'running'
  AND heartbeat_at IS NOT NULL
  AND heartbeat_at < (now() AT TIME ZONE 'UTC') - make_interval(secs => ${operation_stale})"); then
                if [ "${stale_running:-0}" -gt 0 ]; then
                    batch_attention=true
                    _doctor_warn "${stale_running} running batch job(s) have a stale operation heartbeat (threshold=${operation_stale}s); inspect the admin operations page (not a required failure)"
                fi
            fi
        fi
    fi

    if [ "$recovery" -gt 0 ]; then
        _DOCTOR_POST_BATCH_STATE="attention"
        _doctor_warn "Batch jobs require recovery: recovery=${recovery} active=${active} queued=${queued} oldest_queued=$(_doctor_post_age_label "$queued_age") oldest_active=$(_doctor_post_age_label "$active_age"); inspect the admin operations page (not a required failure)"
    elif [ "$active" -gt 0 ]; then
        if $batch_attention; then
            _DOCTOR_POST_BATCH_STATE="attention"
        else
            _DOCTOR_POST_BATCH_STATE="present"
        fi
        _doctor_info "Batch jobs: active=${active} queued=${queued} recovery=0 oldest_queued=$(_doctor_post_age_label "$queued_age") oldest_active=$(_doctor_post_age_label "$active_age")"
    else
        _DOCTOR_POST_BATCH_STATE="present"
        _doctor_info "Batch jobs: no active or recovery rows"
    fi
}

_doctor_post_upgrade() {
    _DOCTOR_POST_EXPECTED_VERSION="$(_doctor_post_resolve_expected_version)"

    step "Post-upgrade deployment verification"
    _doctor_info "Read-only mode: no volumes, migrations, containers, images, or jobs are changed"
    _doctor_info "Expected release version: ${_DOCTOR_POST_EXPECTED_VERSION}"

    if [[ ! "$_DOCTOR_POST_EXPECTED_VERSION" =~ ^[A-Za-z0-9._+-]{1,64}$ ]]; then
        die "Expected release version is not a valid release identifier: ${_DOCTOR_POST_EXPECTED_VERSION}"
    fi

    # Validate recovery timing conventions before classifying heartbeats or
    # recovery-scan freshness. This is read-only and does not touch the stack.
    _doctor_check_recovery_config

    # Load the database/schema view used by the required journal checks.
    _doctor_load_schema

    _doctor_post_check_engine
    _doctor_post_check_stack
    _doctor_post_check_api
    _doctor_post_check_images
    _doctor_post_check_schema
    _doctor_post_check_worker
    _doctor_post_check_beat
    _doctor_post_check_recovery
    _doctor_post_check_batch_jobs

    echo ""
    _doctor_info "Post-upgrade probe summary: services=${_DOCTOR_POST_STACK_STATE} api=${_DOCTOR_POST_API_STATE} images=${_DOCTOR_POST_IMAGE_STATE} schema=${_DOCTOR_POST_SCHEMA_STATE} worker=${_DOCTOR_POST_WORKER_STATE} beat=${_DOCTOR_POST_BEAT_STATE} recovery=${_DOCTOR_POST_RECOVERY_STATE} batch=${_DOCTOR_POST_BATCH_STATE}"
    _doctor_info "Post-upgrade versions: expected=${_DOCTOR_POST_EXPECTED_VERSION} observed=${_DOCTOR_POST_OBSERVED_VERSION:-unavailable}"

    if [ "$_DOCTOR_FAIL" -gt 0 ]; then
        die "Post-upgrade verification failed: ${_DOCTOR_FAIL} required check(s) failed, ${_DOCTOR_WARN} warning(s); fix the failures above before resuming traffic"
    fi
    if [ "$_DOCTOR_WARN" -gt 0 ]; then
        warn "Post-upgrade verification passed with ${_DOCTOR_WARN} warning(s); review above"
    else
        ok "Post-upgrade verification passed"
    fi
}
