# NukeLab OWASP Top 10 Audit

> **Scope:** OWASP Top 10 for Web Applications (2021) assessment of the NukeLab platform  
> **Status:** Complete  
> **Last Updated:** 2026-06-25  
> **Auditor:** Automated audit + code review  
> **Tools Used:** Bandit, pip-audit, npm audit, Dependabot  

---

## Executive Summary

This document records the OWASP Top 10 audit performed against the NukeLab platform. For each risk category we identify the applicable attack surface, the controls currently implemented, any residual gaps, and the remediation status. The platform passes the audit with no critical gaps; remaining items are tracked as future hardening.

---

## A01: Broken Access Control

| Item | Status | Evidence |
|------|--------|----------|
| Granular RBAC with 6+ roles and 20+ permissions | ✅ Implemented | `backend/app/core/roles.py`, `backend/app/core/security.py` |
| Route-level permission decorators | ✅ Implemented | All admin/API routers use `check_permission` / dependencies |
| User can only access own servers by default | ✅ Implemented | Server endpoints validate `server.user_id` against current user |
| Admin server access requires `servers:access_all` | ✅ Implemented | Permission matrix in `backend/app/core/roles.py` |
| JWT-only for bulk / high-impact admin actions | ✅ Implemented | Bulk routers require session JWT (`backend/app/api/bulk.py`) |
| API tokens scoped to least privilege | ✅ Implemented | `backend/app/api/tokens.py` with 24 granular scopes |
| IP allowlist/blocklist middleware | ✅ Implemented | `backend/app/middleware/ip_restriction.py` |
| Impersonation restricted to super_admin | ✅ Implemented | `users:impersonate` permission |

**Residual Gaps / Notes:**

- Periodic access-review workflow for admin roles is a procedural control outside the codebase.

**Risk Rating:** Low

---

## A02: Cryptographic Failures

| Item | Status | Evidence |
|------|--------|----------|
| JWT access tokens (short-lived, 15 min) | ✅ Implemented | `JWT_EXPIRE_MINUTES=15` in `.env.example` |
| Refresh token rotation & cleanup | ✅ Implemented | `backend/app/api/auth.py` periodic cleanup task |
| bcrypt password hashing (12 rounds default) | ✅ Implemented | `LOCAL_AUTH_BCRYPT_ROUNDS=12` |
| Production secret validation | ✅ Implemented | App refuses to start with default `JWT_SECRET` / `SESSION_SECRET` |
| HTTPS / TLS termination via Traefik | ✅ Implemented | `infrastructure/traefik/` Let's Encrypt resolver |
| HSTS header on HTTPS responses | ✅ Implemented | `backend/app/core/security_headers_asgi.py` |
| Session cookies: HttpOnly, Secure, SameSite | ✅ Implemented | `.env.example` + `backend/app/api/auth.py` |
| Sensitive data not logged | ✅ Implemented | Sentry PII scrubbing, structured logging filters |

**Residual Gaps / Notes:**

- RS256 key rotation is not automated; manual procedure documented in operations guides.

**Risk Rating:** Low

---

## A03: Injection

| Item | Status | Evidence |
|------|--------|----------|
| SQL injection prevention (SQLAlchemy ORM + parameterized queries) | ✅ Implemented | All DB access via SQLAlchemy models/repositories |
| Input validation with Pydantic v2 | ✅ Implemented | All API request/response schemas |
| Command injection prevention in container spawning | ✅ Implemented | Docker SDK used directly; no shell interpolation |
| Path traversal prevention | ✅ Implemented | `backend/app/core/security.py` `secure_path()` helper |
| Avatar filename whitelist | ✅ Implemented | Avatar endpoint validates allowed extensions |
| XSS: Content-Security-Policy header | ✅ Implemented | `backend/app/core/security_headers_asgi.py` |
| Output encoding in frontend | ✅ Implemented | React 19 auto-escapes JSX output |

**Residual Gaps / Notes:**

- None identified.

**Risk Rating:** Low

---

## A04: Insecure Design

| Item | Status | Evidence |
|------|--------|----------|
| Rate limiting (per-user + global DDoS) | ✅ Implemented | `backend/app/middleware/rate_limit.py` + Traefik |
| Resource quotas & credit system | ✅ Implemented | NUKE currency, quota service, plan limits |
| Queue-based scheduling when resources unavailable | ✅ Implemented | `backend/app/services/resource_pool_service.py` |
| Idle / max-runtime auto-stop | ✅ Implemented | Server plans + Celery cleanup tasks |
| Request body size limits | ✅ Implemented | `backend/app/middleware/request_size_limit.py` (10 MB default) |
| Maintenance mode with graceful draining | ✅ Implemented | `backend/app/middleware/maintenance.py` |
| Bulk operations limited to JWT session auth | ✅ Implemented | Prevents automation tokens from high-impact bulk actions |

**Residual Gaps / Notes:**

- Formal threat-modeling document is not yet written.

**Risk Rating:** Low

---

## A05: Security Misconfiguration

| Item | Status | Evidence |
|------|--------|----------|
| Debug mode disabled by default in production | ✅ Implemented | `APP_DEBUG=false` guidance in `.env.example` |
| Default secrets rejected in production | ✅ Implemented | Production startup validation |
| Security headers on all responses (including 500s) | ✅ Implemented | Exception-safe ASGI middleware |
| Traefik dashboard disabled in default config | ✅ Implemented | Removed `api.insecure` from Traefik config |
| Removed harmful `browserXssFilter` | ✅ Implemented | Traefik config updated |
| Minimal server footprint (Vite SPA static files) | ✅ Implemented | No Node.js runtime in production frontend |
| Environment files excluded from git | ✅ Implemented | `.gitignore` for `.env`, `.env.development` |
| Permissions-Policy / CORP headers | ✅ Implemented | Security headers middleware |

**Residual Gaps / Notes:**

- None. CDN support is configurable via `VITE_CDN_URL`; actual CDN origin provisioning is an external deployment step.

**Risk Rating:** Low

---

## A06: Vulnerable and Outdated Components

| Item | Status | Evidence |
|------|--------|----------|
| Dependabot configured for pip + npm + GitHub Actions | ✅ Implemented | `.github/dependabot.yml` |
| Python dependency audit (pip-audit) | ✅ Implemented | `./nukelabctl security` runs `pip-audit` |
| Node.js dependency audit (npm audit) | ✅ Implemented | `./nukelabctl security` runs `npm audit` |
| CI security scan workflow | ✅ Implemented | `.github/workflows/security.yml` |
| Pinned dependency versions | ✅ Implemented | `backend/requirements*.txt`, `frontend/package-lock.json` |
| Production deps cleared of known CVEs | ✅ Implemented | `pip-audit` reports 0 vulns for `requirements.txt`; `npm audit` reports 0 vulns |
| python-jose replaced with PyJWT | ✅ Implemented | `backend/requirements.txt`; removes vulnerable `pyasn1` transitive dep |

**Residual Gaps / Notes:**

- pytest 8.3.5 in dev requirements has an accepted local-only tmpdir CVE (GHSA-6w46-j5rx-g56g); blocked from upgrade by pytest-asyncio compatibility. Ignored in CI via `--ignore-vuln`.
- Container image scanning (Trivy/Grype) not yet integrated; recommended before production image builds.

**Risk Rating:** Low

---

## A07: Identification and Authentication Failures

| Item | Status | Evidence |
|------|--------|----------|
| Strong password hashing | ✅ Implemented | bcrypt 12 rounds |
| JWT short expiry + refresh rotation | ✅ Implemented | Auth endpoints + cleanup task |
| OAuth2 / OIDC with PKCE | ✅ Implemented | `OAUTH_PKCE_ENABLED=true` |
| Account lockout / failed-attempt tracking | ✅ Implemented | User model `security` JSONB field |
| Session invalidation on logout | ✅ Implemented | Clears cookies, refresh tokens blacklisted |
| CSRF double-submit protection | ✅ Implemented | `backend/app/middleware/csrf.py` |
| Secure cookie attributes | ✅ Implemented | HttpOnly, Secure, SameSite |

**Residual Gaps / Notes:**

- MFA/TOTP is not implemented.

**Risk Rating:** Low

---

## A08: Software and Data Integrity Failures

| Item | Status | Evidence |
|------|--------|----------|
| Immutable audit log | ✅ Implemented | `backend/app/middleware/audit.py` append-only |
| Immutable NUKE transaction ledger | ✅ Implemented | `CreditTransaction` model |
| Version-pinned dependencies | ✅ Implemented | Locked requirements and lockfile |
| Code review / protected main branch | 🟡 Process | Enforced via GitHub repository settings (out of codebase) |
| Signed commits / artifact signing | ❌ Not implemented | Recommended for CI/CD hardening |

**Residual Gaps / Notes:**

- Signed commits and artifact signing are process/CI controls not yet implemented.

**Risk Rating:** Medium (process-dependent)

---

## A09: Security Logging and Monitoring Failures

| Item | Status | Evidence |
|------|--------|----------|
| Structured JSON logging with correlation IDs | ✅ Implemented | `backend/app/core/logging.py`, `context.py` |
| Request metrics (latency, status, percentiles) | ✅ Implemented | `backend/app/middleware/request_metrics.py` |
| Audit middleware logs all state-changing requests | ✅ Implemented | `backend/app/middleware/audit.py` |
| Sentry error tracking integration | ✅ Implemented | `backend/app/core/sentry.py`, frontend Sentry SDK |
| Prometheus + Grafana dashboards | ✅ Implemented | `backend/app/core/prometheus_metrics.py` |
| Distributed tracing (OpenTelemetry + Jaeger) | ✅ Implemented | `backend/app/core/tracing.py` |
| 30-day retention for request metrics | ✅ Implemented | Celery cleanup task |

**Residual Gaps / Notes:**

- Centralized log aggregator (Loki/ELK) not configured.

**Risk Rating:** Low

---

## A10: Server-Side Request Forgery (SSRF)

| Item | Status | Evidence |
|------|--------|----------|
| Path traversal prevention | ✅ Implemented | `secure_path()` with `Path.resolve()` + `relative_to()` |
| URL validation on user-provided resources | ✅ Implemented | Pydantic `HttpUrl` where applicable |
| Internal metadata endpoints restricted | ✅ Implemented | `/api/metrics` gated by Traefik ForwardAuth |
| Docker socket not exposed to user containers | ✅ Implemented | User containers run on isolated Docker network |
| No user-controlled outbound webhooks | ✅ Implemented | Webhook URLs configured by admins only |

**Residual Gaps / Notes:**

- None identified.

**Risk Rating:** Low

---

## Summary

| OWASP Category | Rating |
|----------------|--------|
| A01 Broken Access Control | Low |
| A02 Cryptographic Failures | Low |
| A03 Injection | Low |
| A04 Insecure Design | Low |
| A05 Security Misconfiguration | Low |
| A06 Vulnerable and Outdated Components | Low |
| A07 Identification and Authentication Failures | Low |
| A08 Software and Data Integrity Failures | Medium |
| A09 Security Logging and Monitoring Failures | Low |
| A10 Server-Side Request Forgery | Low |

**Overall Audit Result:** Pass ✅

No critical or high-severity gaps remain. The medium-rated item (A08) is process-dependent and should be addressed through repository branch protection, signed commits, and CI artifact signing rather than application code changes.

---

## Running the Scans

```bash
# Run all security scanners (production dependencies only)
./nukelabctl security

# Backend only
./nukelabctl security --backend-only

# Include dev dependencies in pip-audit
./nukelabctl security --with-dev

# Skip npm audit
./nukelabctl security --no-npm-audit

# Allow moderate npm findings without failing
./nukelabctl security --fail-on-high=false

# Only report Bandit high-severity issues
./nukelabctl security --bandit-severity=high
```

Reports are written to `backend/reports/security/`.
