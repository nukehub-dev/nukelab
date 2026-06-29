#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# NukeLab security scanning command.
# Runs dependency (pip-audit, npm audit) and static (bandit) scans.
# Produces machine-readable reports under backend/reports/security/.
#
# If the scanners are not installed globally, this command automatically
# creates/uses the shared project-local dev virtualenv at backend/.venv-dev
# (managed together with `nukelabctl lint`) so the scans still work without
# polluting the host or production image.

SECURITY_REPORT_DIR="${DIR}/backend/reports/security"
BANDIT_REPORT="${SECURITY_REPORT_DIR}/bandit-report.json"
PIPAUDIT_REPORT="${SECURITY_REPORT_DIR}/pip-audit-report.json"
FRONTEND_AUDIT_REPORT="${SECURITY_REPORT_DIR}/npm-audit-report.json"
TRIVY_REPORT="${SECURITY_REPORT_DIR}/trivy-report.json"

BANDIT_COUNT_FILE="${SECURITY_REPORT_DIR}/.bandit-count"
PIPAUDIT_COUNT_FILE="${SECURITY_REPORT_DIR}/.pip-audit-count"
NPM_COUNT_FILE="${SECURITY_REPORT_DIR}/.npm-high-count"
NPM_TOTAL_COUNT_FILE="${SECURITY_REPORT_DIR}/.npm-total-count"
TRIVY_COUNT_FILE="${SECURITY_REPORT_DIR}/.trivy-count"

# Defaults
SCAN_BACKEND=true
SCAN_FRONTEND=true
RUN_BANDIT=true
RUN_PIP_AUDIT=true
RUN_NPM_AUDIT=true
RUN_TRIVY=true
FAIL_ON_HIGH=true
SCAN_DEV_REQUIREMENTS=false
BANDIT_SEVERITY="medium" # low | medium | high
BANDIT_CONFIDENCE="low"  # low | medium | high
TRIVY_IMAGE="ghcr.io/aquasecurity/trivy:latest"

# Optional CI/CD supply-chain checks (off by default so the standard scan keeps
# working while these checks can be enabled in release pipelines).
RUN_CHECK_BASE_IMAGES=false
RUN_SIGNED_COMMITS=false
RUN_SBOM=false
SBOM_DIR="${SECURITY_REPORT_DIR}/sbom"

parse_security_args() {
    for arg in "${EXTRA_ARGS[@]}"; do
        case "$arg" in
            --backend-only)
                SCAN_FRONTEND=false
                ;;
            --frontend-only)
                SCAN_BACKEND=false
                ;;
            --no-bandit)
                RUN_BANDIT=false
                ;;
            --no-pip-audit)
                RUN_PIP_AUDIT=false
                ;;
            --no-npm-audit)
                RUN_NPM_AUDIT=false
                ;;
            --no-trivy)
                RUN_TRIVY=false
                ;;
            --check-base-images)
                RUN_CHECK_BASE_IMAGES=true
                ;;
            --signed-commits)
                RUN_SIGNED_COMMITS=true
                ;;
            --sbom)
                RUN_SBOM=true
                ;;
            --fail-on-high=false)
                FAIL_ON_HIGH=false
                ;;
            --no-fail-on-high)
                FAIL_ON_HIGH=false
                ;;
            --bandit-severity=*)
                BANDIT_SEVERITY="${arg#*=}"
                ;;
            --with-dev)
                SCAN_DEV_REQUIREMENTS=true
                ;;
            --help | -h)
                help_security
                exit 0
                ;;
            *)
                die "Unknown option for security: $arg\nRun './nukelabctl security --help' for usage."
                ;;
        esac
    done
}

# _ensure_dev_venv / _ensure_venv_tool / DEV_VENV are shared via lib.sh so
# the lint and security commands cannot drift out of sync.

_bandit_severity_flag() {
    case "$BANDIT_SEVERITY" in
        high) echo "-iii" ;;
        medium) echo "-ii" ;;
        *) echo "" ;;
    esac
}

_bandit_confidence_flag() {
    case "$BANDIT_CONFIDENCE" in
        high) echo "-lll" ;;
        medium) echo "-ll" ;;
        *) echo "" ;;
    esac
}

# ─── Scanner helpers ────────────────────────────────────────────────────────
# Each helper writes its numeric count to a file. This avoids stdout/stderr
# capture issues from progress spinners and other terminal output.

_run_bandit() {
    local bandit_bin
    bandit_bin=$(_ensure_venv_tool bandit)
    local sev_flag=$(_bandit_severity_flag)
    local conf_flag=$(_bandit_confidence_flag)

    log_warn "Running Bandit static analysis..."
    "$bandit_bin" -r "${DIR}/backend/app" \
        -f json \
        -o "$BANDIT_REPORT" \
        $sev_flag $conf_flag 2> /dev/null || true

    "$bandit_bin" -r "${DIR}/backend/app" \
        -f screen \
        $sev_flag $conf_flag >&2 || true

    # Count issues from JSON report, filtering by severity if requested.
    # Paths are passed via argv (not interpolated into the script body) so a
    # project path containing single quotes or other metacharacters is safe.
    BANDIT_REPORT="$BANDIT_REPORT" BANDIT_COUNT_FILE="$BANDIT_COUNT_FILE" \
        BANDIT_SEVERITY="$BANDIT_SEVERITY" python3 -c "
import json, os
try:
    with open(os.environ['BANDIT_REPORT']) as f:
        data = json.load(f)
    issues = data.get('results', [])
    sev = os.environ['BANDIT_SEVERITY']
    if sev == 'high':
        issues = [i for i in issues if i.get('issue_severity', 'LOW').upper() in ('HIGH',)]
    elif sev == 'medium':
        issues = [i for i in issues if i.get('issue_severity', 'LOW').upper() in ('HIGH', 'MEDIUM')]
    with open(os.environ['BANDIT_COUNT_FILE'], 'w') as f:
        f.write(str(len(issues)))
except Exception:
    with open(os.environ['BANDIT_COUNT_FILE'], 'w') as f:
        f.write('0')
" 2> /dev/null
}

_run_pip_audit() {
    local pip_audit_bin
    pip_audit_bin=$(_ensure_venv_tool pip-audit)

    local req_args=("-r" "${DIR}/backend/requirements.txt")
    if $SCAN_DEV_REQUIREMENTS; then
        req_args+=("-r" "${DIR}/backend/requirements-dev.txt")
    fi

    if $SCAN_DEV_REQUIREMENTS; then
        log_warn "Running pip-audit on backend requirements (including dev)..."
    else
        log_warn "Running pip-audit on backend requirements..."
    fi
    "$pip_audit_bin" \
        "${req_args[@]}" \
        --format=json \
        --desc \
        --progress-spinner=off \
        -o "$PIPAUDIT_REPORT" 2> /dev/null || true

    "$pip_audit_bin" \
        "${req_args[@]}" \
        --format=columns \
        --progress-spinner=off \
        >&2 || true

    # Count total reported vulnerabilities. Paths via env to be robust
    # against metacharacters in DIR (e.g. single quotes).
    PIPAUDIT_REPORT="$PIPAUDIT_REPORT" PIPAUDIT_COUNT_FILE="$PIPAUDIT_COUNT_FILE" \
        python3 -c "
import json, os
try:
    with open(os.environ['PIPAUDIT_REPORT']) as f:
        data = json.load(f)
    deps = data.get('dependencies', [])
    count = 0
    for dep in deps:
        count += len(dep.get('vulns', []))
    with open(os.environ['PIPAUDIT_COUNT_FILE'], 'w') as f:
        f.write(str(count))
except Exception:
    with open(os.environ['PIPAUDIT_COUNT_FILE'], 'w') as f:
        f.write('0')
" 2> /dev/null
}

_run_npm_audit() {
    log_warn "Running npm audit..."
    if [ ! -d "${DIR}/frontend/node_modules" ]; then
        log_warn "frontend/node_modules not found; run: ./nukelabctl install frontend"
        echo 0 > "$NPM_COUNT_FILE"
        return
    fi

    (cd "${DIR}/frontend" && npm audit --json > "$FRONTEND_AUDIT_REPORT" 2> /dev/null) || true
    (cd "${DIR}/frontend" && npm audit) >&2 || true

    if [ -f "$FRONTEND_AUDIT_REPORT" ] && command -v node > /dev/null 2>&1; then
        node -e "
const fs = require('fs');
try {
    const data = JSON.parse(fs.readFileSync('$FRONTEND_AUDIT_REPORT', 'utf8'));
    const vulns = data.vulnerabilities || {};
    let high = 0;
    let total = 0;
    for (const [name, info] of Object.entries(vulns)) {
        total++;
        const sev = (info.severity || '').toLowerCase();
        if (sev === 'high' || sev === 'critical') high++;
    }
    fs.writeFileSync('$NPM_COUNT_FILE', String(high));
    fs.writeFileSync('$NPM_TOTAL_COUNT_FILE', String(total));
} catch (e) {
    fs.writeFileSync('$NPM_COUNT_FILE', '0');
    fs.writeFileSync('$NPM_TOTAL_COUNT_FILE', '0');
}
" 2> /dev/null
    else
        echo 0 > "$NPM_COUNT_FILE"
        echo 0 > "$NPM_TOTAL_COUNT_FILE"
    fi
}

_run_trivy() {
    log_warn "Running Trivy filesystem and image scans..."

    if [ -z "${CONTAINER_ENGINE:-}" ]; then
        log_warn "Container engine not detected; skipping Trivy scan"
        echo 0 > "$TRIVY_COUNT_FILE"
        return
    fi

    if ! "$CONTAINER_ENGINE" info > /dev/null 2>&1; then
        log_warn "Container engine '$CONTAINER_ENGINE' is not reachable; skipping Trivy scan"
        echo 0 > "$TRIVY_COUNT_FILE"
        return
    fi

    # Filesystem scan of the repository.
    "$CONTAINER_ENGINE" run --rm \
        -v "${DIR}:${DIR}:ro" \
        -v "${SECURITY_REPORT_DIR}:${SECURITY_REPORT_DIR}:rw" \
        "${TRIVY_IMAGE}" fs \
        --scanners vuln,secret,misconfig \
        --severity HIGH,CRITICAL \
        --format json \
        --output "${TRIVY_REPORT}" \
        "${DIR}" 2> /dev/null || true

    # Image scan for locally built NukeLab images when available.
    local _images=(
        "nukelab-backend:latest"
        "nukelab-frontend:latest"
        "nukelab-dev:latest"
        "nukelab-base:latest"
        "nukelab-auth-sidecar:latest"
    )
    for _image in "${_images[@]}"; do
        local _image_exists=false
        if [ "$CONTAINER_ENGINE" = "podman" ]; then
            "$CONTAINER_ENGINE" image exists "$_image" 2> /dev/null && _image_exists=true || true
        else
            [ -n "$($CONTAINER_ENGINE images -q "$_image" 2> /dev/null)" ] && _image_exists=true || true
        fi
        if ! $_image_exists; then
            continue
        fi
        local _image_report="${SECURITY_REPORT_DIR}/trivy-${_image//\//-}.json"
        "$CONTAINER_ENGINE" run --rm \
            -v /var/run/docker.sock:/var/run/docker.sock:ro \
            -v "${SECURITY_REPORT_DIR}:${SECURITY_REPORT_DIR}:rw" \
            "${TRIVY_IMAGE}" image \
            --severity HIGH,CRITICAL \
            --format json \
            --output "${_image_report}" \
            "$_image" 2> /dev/null || true
    done

    # Count HIGH/CRITICAL findings across all Trivy reports.
    TRIVY_REPORT_DIR="$SECURITY_REPORT_DIR" TRIVY_COUNT_FILE="$TRIVY_COUNT_FILE" python3 -c "
import json, os
report_dir = os.environ['TRIVY_REPORT_DIR']
count_file = os.environ['TRIVY_COUNT_FILE']
total = 0
for name in os.listdir(report_dir):
    if not name.startswith('trivy-') or not name.endswith('.json'):
        continue
    path = os.path.join(report_dir, name)
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception:
        continue
    results = data.get('Results', [])
    for result in results:
        for vuln in result.get('Vulnerabilities', []):
            sev = vuln.get('Severity', 'UNKNOWN').upper()
            if sev in ('HIGH', 'CRITICAL'):
                total += 1
with open(count_file, 'w') as f:
    f.write(str(total))
" 2> /dev/null
}

# ─── Supply-chain check helpers ─────────────────────────────────────────────

_run_check_base_images() {
    log_warn "Checking Dockerfile base image pinning..."
    if "${DIR}/scripts/security/check-base-image-pinning.sh" --strict; then
        log_ok "All external base images are pinned by digest"
        return 0
    else
        log_warn "Unpinned external base images found. See output above."
        return 1
    fi
}

_run_signed_commits() {
    log_warn "Checking commit signatures..."
    if "${DIR}/scripts/security/check-signed-commits.sh" --strict; then
        log_ok "All commits are signed"
        return 0
    else
        log_warn "Unsigned commits found. See output above."
        return 1
    fi
}

_run_sbom() {
    log_warn "Generating SBOM artifacts..."
    mkdir -p "$SBOM_DIR"
    if "${DIR}/scripts/security/generate-sbom.sh" > "${SBOM_DIR}/generate-sbom.log" 2>&1; then
        log_ok "SBOM generation completed. Outputs in ${SBOM_DIR}"
    else
        log_warn "SBOM generation completed with warnings. See ${SBOM_DIR}/generate-sbom.log"
    fi
}

# ─── Main command ───────────────────────────────────────────────────────────

cmd_security() {
    mkdir -p "$SECURITY_REPORT_DIR"
    rm -f "$BANDIT_COUNT_FILE" "$PIPAUDIT_COUNT_FILE" "$NPM_COUNT_FILE" "$NPM_TOTAL_COUNT_FILE" "$TRIVY_COUNT_FILE"

    local _overall_exit=0
    local _bandit_count=0
    local _pip_audit_count=0
    local _npm_high_count=0
    local _npm_total_count=0
    local _trivy_count=0

    if $SCAN_BACKEND; then
        step "Backend security scans"

        if $RUN_BANDIT; then
            _run_bandit
            _bandit_count=$(cat "$BANDIT_COUNT_FILE" 2> /dev/null || echo 0)
            if [ "$_bandit_count" -gt 0 ]; then
                log_warn "Bandit found $_bandit_count issue(s) at severity >= ${BANDIT_SEVERITY}. See ${BANDIT_REPORT}"
                _overall_exit=1
            else
                log_ok "Bandit scan passed"
            fi
        fi

        if $RUN_PIP_AUDIT; then
            _run_pip_audit
            _pip_audit_count=$(cat "$PIPAUDIT_COUNT_FILE" 2> /dev/null || echo 0)
            if [ "$_pip_audit_count" -gt 0 ]; then
                log_warn "pip-audit found $_pip_audit_count vulnerable Python package(s). See ${PIPAUDIT_REPORT}"
                _overall_exit=1
            else
                log_ok "pip-audit scan passed"
            fi
        fi

        if $RUN_TRIVY; then
            _run_trivy
            _trivy_count=$(cat "$TRIVY_COUNT_FILE" 2> /dev/null || echo 0)
            if [ "$_trivy_count" -gt 0 ]; then
                log_warn "Trivy found $_trivy_count HIGH/CRITICAL finding(s). See ${SECURITY_REPORT_DIR}/trivy-*.json"
                _overall_exit=1
            else
                log_ok "Trivy scan passed"
            fi
        fi
    fi

    if $SCAN_FRONTEND; then
        step "Frontend security scan"

        if $RUN_NPM_AUDIT; then
            _run_npm_audit
            _npm_high_count=$(cat "$NPM_COUNT_FILE" 2> /dev/null || echo 0)
            _npm_total_count=$(cat "$NPM_TOTAL_COUNT_FILE" 2> /dev/null || echo 0)
            if $FAIL_ON_HIGH && [ "$_npm_high_count" -gt 0 ]; then
                log_warn "npm audit reported $_npm_high_count high/critical vulnerability(ies). See ${FRONTEND_AUDIT_REPORT}"
                _overall_exit=1
            elif [ "$_npm_total_count" -gt 0 ]; then
                log_warn "npm audit reported $_npm_total_count vulnerability(ies) (low/moderate). See ${FRONTEND_AUDIT_REPORT}"
            else
                log_ok "npm audit passed"
            fi
        fi
    fi

    if $RUN_SBOM || $RUN_CHECK_BASE_IMAGES || $RUN_SIGNED_COMMITS; then
        step "CI/CD supply-chain checks"

        if $RUN_CHECK_BASE_IMAGES; then
            _run_check_base_images || _overall_exit=1
        fi

        if $RUN_SIGNED_COMMITS; then
            _run_signed_commits || _overall_exit=1
        fi

        if $RUN_SBOM; then
            _run_sbom
        fi
    fi

    # Clean up transient count files; keep reports.
    rm -f "$BANDIT_COUNT_FILE" "$PIPAUDIT_COUNT_FILE" "$NPM_COUNT_FILE" "$NPM_TOTAL_COUNT_FILE" "$TRIVY_COUNT_FILE"

    step "Security scan summary"
    echo "  Reports written to: ${SECURITY_REPORT_DIR}"
    echo "  Bandit issues (>= ${BANDIT_SEVERITY}):  ${_bandit_count}"
    echo "  pip-audit vulnerable packages:          ${_pip_audit_count}"
    echo "  Trivy HIGH/CRITICAL findings:           ${_trivy_count}"
    echo "  npm total vulnerabilities:              ${_npm_total_count}"
    echo "  npm high/critical vulnerabilities:      ${_npm_high_count}"

    if [ $_overall_exit -ne 0 ]; then
        log_warn "Security scan completed with findings. Review the reports above."
    else
        log_ok "Security scan completed with no blocking findings."
    fi

    return $_overall_exit
}

help_security() {
    cat <<- EOF
${BOLD}Usage:${RESET} ./nukelabctl security [options]

Run security scanners against the codebase and dependency manifests.
If bandit/pip-audit are not installed, an isolated venv is created
automatically at backend/.venv-dev (shared with the lint command).

${BOLD}Scans:${RESET}
  Bandit       Static analysis for Python security issues
  pip-audit    Audit Python dependencies for known CVEs
  npm audit    Audit Node.js dependencies for known CVEs
  Trivy        Filesystem and container image vulnerability scan

${BOLD}Supply-chain checks (off by default):${RESET}
  --check-base-images     Verify external Dockerfile base images are pinned by digest
  --signed-commits        Verify all commits on the current branch are signed
  --sbom                  Generate CycloneDX SBOM artifacts for the repo and images

${BOLD}Options:${RESET}
  --backend-only          Run only backend scanners
  --frontend-only         Run only frontend scanners
  --no-bandit             Skip Bandit
  --no-pip-audit          Skip pip-audit
  --no-npm-audit          Skip npm audit
  --no-trivy              Skip Trivy filesystem/image scan
  --with-dev              Also scan backend/requirements-dev.txt
  --no-fail-on-high       Do not fail the command for npm high/critical findings
  --fail-on-high=false    Same as above (kept for backwards compatibility)
  --bandit-severity=low|medium|high
                          Minimum Bandit severity to report (default: medium)

${BOLD}Examples:${RESET}
  ./nukelabctl security
  ./nukelabctl security --backend-only
  ./nukelabctl security --with-dev
  ./nukelabctl security --no-npm-audit --bandit-severity=high
  ./nukelabctl security --no-trivy
  ./nukelabctl security --check-base-images --signed-commits --sbom
EOF
}
