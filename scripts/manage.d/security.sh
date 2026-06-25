#!/bin/bash
# NukeLab security scanning command.
# Runs dependency (pip-audit, npm audit) and static (bandit) scans.
# Produces machine-readable reports under backend/reports/security/.
#
# If the scanners are not installed globally, this command automatically
# creates/uses a project-local virtualenv at backend/.venv-security so the
# scans still work without polluting the host or production image.

SECURITY_REPORT_DIR="${DIR}/backend/reports/security"
SECURITY_VENV="${DIR}/backend/.venv-security"
BANDIT_REPORT="${SECURITY_REPORT_DIR}/bandit-report.json"
PIPAUDIT_REPORT="${SECURITY_REPORT_DIR}/pip-audit-report.json"
FRONTEND_AUDIT_REPORT="${SECURITY_REPORT_DIR}/npm-audit-report.json"

BANDIT_COUNT_FILE="${SECURITY_REPORT_DIR}/.bandit-count"
PIPAUDIT_COUNT_FILE="${SECURITY_REPORT_DIR}/.pip-audit-count"
NPM_COUNT_FILE="${SECURITY_REPORT_DIR}/.npm-high-count"

# Defaults
SCAN_BACKEND=true
SCAN_FRONTEND=true
RUN_BANDIT=true
RUN_PIP_AUDIT=true
RUN_NPM_AUDIT=true
FAIL_ON_HIGH=true
BANDIT_SEVERITY="medium"   # low | medium | high
BANDIT_CONFIDENCE="low"    # low | medium | high

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
            --fail-on-high=false)
                FAIL_ON_HIGH=false
                ;;
            --bandit-severity=*)
                BANDIT_SEVERITY="${arg#*=}"
                ;;
            --help|-h)
                help_security
                exit 0
                ;;
            *)
                warn "Unknown option: $arg"
                ;;
        esac
    done
}

# ─── Tool discovery ─────────────────────────────────────────────────────────
# Ensure a tool exists, installing it into the project-local venv if needed.
# Prints the absolute path to the tool on stdout; diagnostics go to stderr.
_ensure_venv_tool() {
    local tool_name="$1"
    local tool_bin="${SECURITY_VENV}/bin/${tool_name}"

    if [ -x "$tool_bin" ]; then
        echo "$tool_bin"
        return 0
    fi

    if command -v "$tool_name" >/dev/null 2>&1; then
        command -v "$tool_name"
        return 0
    fi

    log_warn "${tool_name} not found; creating isolated security venv at ${SECURITY_VENV}..."
    python3 -m venv "$SECURITY_VENV"
    "$SECURITY_VENV/bin/pip" install -q --upgrade pip
    case "$tool_name" in
        bandit)
            "$SECURITY_VENV/bin/pip" install -q 'bandit[toml]>=1.8.2,<2.0'
            ;;
        pip-audit)
            "$SECURITY_VENV/bin/pip" install -q 'pip-audit==2.7.3'
            ;;
    esac

    if [ -x "${SECURITY_VENV}/bin/${tool_name}" ]; then
        echo "${SECURITY_VENV}/bin/${tool_name}"
        return 0
    fi

    die "Failed to install ${tool_name}. Install manually or check network access."
}

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
        $sev_flag $conf_flag 2>/dev/null || true

    "$bandit_bin" -r "${DIR}/backend/app" \
        -f screen \
        $sev_flag $conf_flag >&2 || true

    # Count issues from JSON report, filtering by severity if requested.
    python3 -c "
import json, sys
try:
    with open('$BANDIT_REPORT') as f:
        data = json.load(f)
    issues = data.get('results', [])
    if '$BANDIT_SEVERITY' == 'high':
        issues = [i for i in issues if i.get('issue_severity', 'LOW').upper() in ('HIGH',)]
    elif '$BANDIT_SEVERITY' == 'medium':
        issues = [i for i in issues if i.get('issue_severity', 'LOW').upper() in ('HIGH', 'MEDIUM')]
    with open('$BANDIT_COUNT_FILE', 'w') as f:
        f.write(str(len(issues)))
except Exception:
    with open('$BANDIT_COUNT_FILE', 'w') as f:
        f.write('0')
" 2>/dev/null
}

_run_pip_audit() {
    local pip_audit_bin
    pip_audit_bin=$(_ensure_venv_tool pip-audit)

    log_warn "Running pip-audit on backend requirements..."
    "$pip_audit_bin" \
        -r "${DIR}/backend/requirements.txt" \
        -r "${DIR}/backend/requirements-dev.txt" \
        --format=json \
        --desc \
        --progress-spinner=off \
        -o "$PIPAUDIT_REPORT" 2>/dev/null || true

    "$pip_audit_bin" \
        -r "${DIR}/backend/requirements.txt" \
        -r "${DIR}/backend/requirements-dev.txt" \
        --format=columns \
        --progress-spinner=off \
        >&2 || true

    # Count total reported vulnerabilities.
    python3 -c "
import json, sys
try:
    with open('$PIPAUDIT_REPORT') as f:
        data = json.load(f)
    deps = data.get('dependencies', [])
    count = 0
    for dep in deps:
        count += len(dep.get('vulns', []))
    with open('$PIPAUDIT_COUNT_FILE', 'w') as f:
        f.write(str(count))
except Exception:
    with open('$PIPAUDIT_COUNT_FILE', 'w') as f:
        f.write('0')
" 2>/dev/null
}

_run_npm_audit() {
    log_warn "Running npm audit..."
    if [ ! -d "${DIR}/frontend/node_modules" ]; then
        log_warn "frontend/node_modules not found; run: ./nukelabctl install frontend"
        echo 0 > "$NPM_COUNT_FILE"
        return
    fi

    (cd "${DIR}/frontend" && npm audit --json > "$FRONTEND_AUDIT_REPORT" 2>/dev/null) || true
    (cd "${DIR}/frontend" && npm audit) >&2 || true

    if [ -f "$FRONTEND_AUDIT_REPORT" ] && command -v node >/dev/null 2>&1; then
        node -e "
const fs = require('fs');
try {
    const data = JSON.parse(fs.readFileSync('$FRONTEND_AUDIT_REPORT', 'utf8'));
    const vulns = data.vulnerabilities || {};
    let count = 0;
    for (const [name, info] of Object.entries(vulns)) {
        const sev = (info.severity || '').toLowerCase();
        if (sev === 'high' || sev === 'critical') count++;
    }
    fs.writeFileSync('$NPM_COUNT_FILE', String(count));
} catch (e) {
    fs.writeFileSync('$NPM_COUNT_FILE', '0');
}
" 2>/dev/null
    else
        echo 0 > "$NPM_COUNT_FILE"
    fi
}

# ─── Main command ───────────────────────────────────────────────────────────

cmd_security() {
    mkdir -p "$SECURITY_REPORT_DIR"
    rm -f "$BANDIT_COUNT_FILE" "$PIPAUDIT_COUNT_FILE" "$NPM_COUNT_FILE"

    local _overall_exit=0
    local _bandit_count=0
    local _pip_audit_count=0
    local _npm_high_count=0

    if $SCAN_BACKEND; then
        step "Backend security scans"

        if $RUN_BANDIT; then
            _run_bandit
            _bandit_count=$(cat "$BANDIT_COUNT_FILE" 2>/dev/null || echo 0)
            if [ "$_bandit_count" -gt 0 ]; then
                log_warn "Bandit found $_bandit_count issue(s) at severity >= ${BANDIT_SEVERITY}. See ${BANDIT_REPORT}"
                _overall_exit=1
            else
                log_ok "Bandit scan passed"
            fi
        fi

        if $RUN_PIP_AUDIT; then
            _run_pip_audit
            _pip_audit_count=$(cat "$PIPAUDIT_COUNT_FILE" 2>/dev/null || echo 0)
            if [ "$_pip_audit_count" -gt 0 ]; then
                log_warn "pip-audit found $_pip_audit_count vulnerable Python package(s). See ${PIPAUDIT_REPORT}"
                _overall_exit=1
            else
                log_ok "pip-audit scan passed"
            fi
        fi
    fi

    if $SCAN_FRONTEND; then
        step "Frontend security scan"

        if $RUN_NPM_AUDIT; then
            _run_npm_audit
            _npm_high_count=$(cat "$NPM_COUNT_FILE" 2>/dev/null || echo 0)
            if $FAIL_ON_HIGH && [ "$_npm_high_count" -gt 0 ]; then
                log_warn "npm audit reported $_npm_high_count high/critical vulnerability(ies). See ${FRONTEND_AUDIT_REPORT}"
                _overall_exit=1
            elif [ -s "$FRONTEND_AUDIT_REPORT" ]; then
                log_warn "npm audit reported vulnerabilities. See ${FRONTEND_AUDIT_REPORT}"
            else
                log_ok "npm audit passed"
            fi
        fi
    fi

    # Clean up transient count files; keep reports.
    rm -f "$BANDIT_COUNT_FILE" "$PIPAUDIT_COUNT_FILE" "$NPM_COUNT_FILE"

    step "Security scan summary"
    echo "  Reports written to: ${SECURITY_REPORT_DIR}"
    echo "  Bandit issues (>= ${BANDIT_SEVERITY}):  ${_bandit_count}"
    echo "  pip-audit vulnerable packages:          ${_pip_audit_count}"
    echo "  npm high/critical vulnerabilities:      ${_npm_high_count}"

    if [ $_overall_exit -ne 0 ]; then
        log_warn "Security scan completed with findings. Review the reports above."
    else
        log_ok "Security scan completed with no blocking findings."
    fi

    return $_overall_exit
}

help_security() {
    cat <<-EOF
${BOLD}Usage:${RESET} ./nukelabctl security [options]

Run security scanners against the codebase and dependency manifests.
If bandit/pip-audit are not installed, an isolated venv is created
automatically at backend/.venv-security.

${BOLD}Scans:${RESET}
  Bandit       Static analysis for Python security issues
  pip-audit    Audit Python dependencies for known CVEs
  npm audit    Audit Node.js dependencies for known CVEs

${BOLD}Options:${RESET}
  --backend-only          Run only backend scanners
  --frontend-only         Run only frontend scanners
  --no-bandit             Skip Bandit
  --no-pip-audit          Skip pip-audit
  --no-npm-audit          Skip npm audit
  --fail-on-high=false    Do not fail the command for npm high/critical findings
  --bandit-severity=low|medium|high
                          Minimum Bandit severity to report (default: medium)

${BOLD}Examples:${RESET}
  ./nukelabctl security
  ./nukelabctl security --backend-only
  ./nukelabctl security --no-npm-audit --bandit-severity=high
EOF
}
