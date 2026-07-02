# NukeLab v2.0 — Comprehensive Penetration Test Plan

> **Status:** Draft — Ready for review and scheduling  
> **Version:** 1.0  
> **Last Updated:** 2026-06-28  
> **Target:** Pre-production security validation before public launch  
> **Engagement Type:** Full-stack black-box, grey-box, and white-box assessment  

---

## 1. Executive Summary

NukeLab v2.0 is a multi-user scientific-computing platform built on **Vite + React 19 SPA**, **FastAPI**, **PostgreSQL 18**, **Redis**, **Traefik v3**, and **Docker/Podman**. The platform manages user identity, role-based access control, resource quotas, containerized IDE environments (NukeIDE/Theia), credit billing, audit logging, real-time monitoring, and shared workspaces.

An internal OWASP Top 10 audit (`OWASP-AUDIT.md`) has already been performed and rates the platform as **Pass ✅** with one medium residual risk (A08 — signed commits / artifact signing). However, a formal, independent penetration test is required before production launch to validate:

- Effectiveness of the RBAC and permission enforcement across all privilege levels.
- API authorization boundaries (BOLA/BFLA) for user-owned servers, volumes, workspaces, and credits.
- Container and infrastructure isolation between the host, system services, and user workloads.
- Authentication bypass, session management, and CSRF resilience.
- Business-logic flaws in the NUKE credit system, scheduling, quotas, and bulk operations.
- Security of the CI/CD pipeline and container supply chain.

This document defines scope, methodology, test cases, tools, timeline, deliverables, and acceptance criteria for that engagement.

---

## 2. Objectives & Success Criteria

### 2.1 Primary Objectives

1. **Identify exploitable vulnerabilities** in the web application, REST API, container runtime, and network configuration.
2. **Validate that RBAC and object-level authorization** prevent horizontal and vertical privilege escalation.
3. **Confirm container isolation** so that a compromised user environment cannot escape to the Docker socket, host network, or other users' data.
4. **Test the NUKE credit/billing flow** for logic flaws that could lead to free resource abuse, double-spending, or quota bypass.
5. **Assess the CI/CD supply chain** for secrets leakage, unsigned artifacts, and vulnerable dependencies.
6. **Produce a remediation roadmap** prioritized by risk with evidence, reproduction steps, and retest criteria.

### 2.2 Success Criteria

| ID | Criterion |
|----|-----------|
| SC-01 | No critical or high-severity vulnerabilities remain un-remediated at go-live. |
| SC-02 | All OWASP API Security Top 10 2023 categories are tested and rated. |
| SC-03 | All OWASP Web Top 10 2021 categories are re-tested independently of the internal audit. |
| SC-04 | Container escape attempts from a standard user server are blocked or detected. |
| SC-05 | Bulk admin actions and sensitive endpoints reject API-token authentication as designed. |
| SC-06 | Audit logs capture all successful and failed privilege-escalation attempts tested. |
| SC-07 | A signed, retestable report is delivered with CVSS 4.0 severity ratings. |

---

## 3. Scope

### 3.1 In-Scope Targets

| Layer | Target | Notes |
|-------|--------|-------|
| **Frontend SPA** | `https://nukelab.example.com/app/*` | Vite + React 19, TanStack Router, TanStack Query, shadcn/ui |
| **Backend API** | `https://nukelab.example.com/api/*` | FastAPI, Pydantic v2, SQLAlchemy async |
| **Auth Endpoints** | `/api/auth/*`, OAuth2 callback, refresh, logout | Local + NukeHub OAuth modes |
| **User Containers** | `/user/{username}/{serverName}/*` | NukeIDE (Theia + Nginx JWT proxy) |
| **WebSocket** | `/api/ws/*` | Real-time metrics and notifications |
| **Metrics/Prometheus** | `/api/metrics` | Gated by Traefik ForwardAuth |
| **Reverse Proxy** | Traefik v3 static + dynamic config | `infrastructure/traefik/` |
| **Container Runtime** | Docker/Podman daemon, user containers, networks, volumes | Including capability drops, seccomp, AppArmor/SELinux |
| **Database** | PostgreSQL 18 + PgBouncer | Credential storage, connection strings, access controls |
| **Cache/Queue** | Redis | Session storage, Celery broker, pub/sub |
| **CI/CD** | `.github/workflows/*.yml`, container images, GHCR registry | Supply-chain and secret-exposure review |
| **Source Code** | Full monorepo (white-box review) | `backend/`, `frontend/`, `environments/`, `scripts/` |

### 3.2 Out-of-Scope

- Third-party NukeHub Auth service infrastructure (only the integration callback/JWT validation is in scope).
- Physical security of the data center.
- Social-engineering attacks against NukeLab staff or users.
- Denial-of-Service testing that degrades shared non-production environments beyond agreed windows.
- Wireless network penetration testing.

### 3.3 Test Accounts Required

| Role | Quantity | Purpose |
|------|----------|---------|
| `super_admin` | 2 | Test highest-privilege actions and impersonation |
| `admin` | 2 | Test user/server management and server access |
| `moderator` | 2 | Test user CRUD without server access |
| `support` | 2 | Test server access with audit trail |
| `user` | 4 | BOLA/IDOR testing across servers, volumes, workspaces |
| `guest` | 2 | Test least-privilege and quota restrictions |
| API-only tokens | 6 | Scoped tokens for automation abuse tests |

---

## 4. Testing Methodology

The engagement follows **OWASP Web Security Testing Guide (WSTG)**, **OWASP API Security Top 10 2023**, **PTES** (Penetration Testing Execution Standard), and **CISA Vulnerability Disclosure** best practices. Testing is performed from three perspectives:

1. **Black-box:** No credentials or source access; simulate external attacker.
2. **Grey-box:** Authenticated user accounts; simulate compromised user.
3. **White-box:** Full source access and architecture review; simulate insider / advanced threat.

### 4.1 Engagement Phases

```
Phase 1: Reconnaissance & Asset Discovery
Phase 2: Architecture & Configuration Review (white-box)
Phase 3: Authentication & Session Management Testing
Phase 4: Authorization Testing (RBAC, BOLA, BFLA)
Phase 5: Input Validation & Injection Testing
Phase 6: Business Logic Testing
Phase 7: Container & Infrastructure Testing
Phase 8: CI/CD & Supply-Chain Review
Phase 9: Reporting & Prioritization
Phase 10: Remediation Support & Retest
```

---

## 5. Detailed Test Cases

### 5.1 Phase 1 — Reconnaissance & Asset Discovery

| ID | Test | Tool / Technique | Expected Control |
|----|------|------------------|------------------|
| REC-01 | Enumerate public subdomains and exposed services | Subfinder, amass, dnsrecon | Only intended services exposed; no admin/debug panels public |
| REC-02 | Fuzz hidden API endpoints and versions | ffuf, Kiterunner | Undocumented/internal endpoints return 401/403 or 404 |
| REC-03 | Discover JavaScript assets and hardcoded API keys | Burp JS Link Finder, LinkFinder.py | No secrets, internal IPs, or debug endpoints in frontend bundles |
| REC-04 | Identify technology stack and versions | Wappalyzer, WhatWeb, response headers | No version leakage; headers stripped by Traefik |
| REC-05 | Map OpenAPI/Swagger if exposed | `/api/docs`, `/openapi.json` | Docs gated or disabled in production |
| REC-06 | Review certificate transparency and DNS records | crt.sh, SecurityTrails | No dangling or attacker-controlled records |

### 5.2 Phase 2 — Architecture & Configuration Review

| ID | Test | Target Files / Components | Expected Control |
|----|------|---------------------------|------------------|
| CFG-01 | Review RBAC permission matrix | `backend/app/core/roles.py` | Least privilege; no dangerous wildcard permissions |
| CFG-02 | Review JWT validation, secret handling, token lifetimes | `backend/app/core/security.py`, `backend/app/api/auth.py` | HS256/RS256, short expiry, secure rotation, default secrets rejected |
| CFG-03 | Review security headers middleware | `backend/app/core/security_headers_asgi.py` | CSP, HSTS, CORP, Permissions-Policy, Cache-Control on all responses |
| CFG-04 | Review rate limiting implementation | `backend/app/middleware/rate_limit.py` | Tiered per-user limits; bulk endpoints stricter |
| CFG-05 | Review CSRF double-submit protection | `backend/app/middleware/csrf.py` | State-changing cookie-authenticated requests require matching token |
| CFG-06 | Review IP allowlist/blocklist middleware | `backend/app/middleware/ip_restriction.py` | CIDR support; self-block prevention; auth/health exempt |
| CFG-07 | Review request size limits | `backend/app/middleware/request_size_limit.py` | 10 MB default; chunked-transfer abort |
| CFG-08 | Review path traversal prevention | `backend/app/core/security.py::secure_path()` | `Path.resolve()` + `relative_to()` validation; whitelist for avatars |
| CFG-09 | Review Docker spawner security options | `backend/app/container/spawner.py` | Non-root user, read-only root fs, no new privileges, capability drop, seccomp |
| CFG-10 | Review Traefik TLS and middleware config | `infrastructure/traefik/traefik.yml`, `dynamic/*.yml` | TLS 1.3, no insecure dashboard, no browserXssFilter |
| CFG-11 | Review environment variable and secret handling | `.env.example`, compose files, CI secrets | No hardcoded secrets; production validation refuses defaults |

### 5.3 Phase 3 — Authentication & Session Management

| ID | Test | Endpoint / Flow | Expected Result |
|----|------|-----------------|-----------------|
| AUTH-01 | Brute-force login rate limiting | `POST /api/auth/login` | Account lockout or 429 after repeated failures; no user enumeration via timing |
| AUTH-02 | Credential stuffing | `POST /api/auth/login` | 429 and/or account lockout; no bypass via X-Forwarded-For |
| AUTH-03 | JWT `alg: none` attack | Any Bearer-protected endpoint | Signature verification enforced; tampered token rejected |
| AUTH-04 | JWT algorithm confusion (RS256 → HS256) | Any Bearer-protected endpoint | Rejects HS256 when RS256 is configured |
| AUTH-05 | JWT weak secret brute-force | Capture token, run hashcat | HMAC secret not brute-forceable; 12+ char random secret |
| AUTH-06 | Token expiration and refresh rotation | `POST /api/auth/refresh`, logout | Old refresh token invalidated after rotation |
| AUTH-07 | Session cookie flags | Login response headers | `HttpOnly`, `Secure`, `SameSite=Lax/Strict` on production |
| AUTH-08 | OAuth2 redirect_uri manipulation | `POST /api/auth/oauth/callback` | Strict redirect URI validation; PKCE enforced |
| AUTH-09 | Password reset flow | `POST /api/auth/reset-request` | No account enumeration; tokens cryptographically random; expire |
| AUTH-10 | CSRF on cookie-authenticated state changes | Any `POST/PUT/DELETE` via browser | 403 without valid `X-CSRF-Token` header matching cookie |
| AUTH-11 | API token scope enforcement | `Authorization: Token <token>` | Scoped token cannot perform actions outside granted scopes |
| AUTH-12 | API token on bulk/sensitive endpoints | `POST /api/bulk/*`, `/api/admin/*` | Bulk endpoints reject API tokens and require session JWT |
| AUTH-13 | MFA readiness assessment | N/A | Document absence of TOTP/WebAuthn MFA as a finding if required |

### 5.4 Phase 4 — Authorization Testing (RBAC, BOLA, BFLA)

#### 4.1 Horizontal Privilege Escalation (BOLA / IDOR)

| ID | Test | Endpoint Pattern | Expected Result |
|----|------|------------------|-----------------|
| BOLA-01 | Access another user's server details | `GET /api/servers/{server_id}` | 403 unless actor has `servers:read_all` |
| BOLA-02 | Start/stop/restart another user's server | `POST /api/servers/{id}/start` | 403 unless `servers:access_all` |
| BOLA-03 | Access another user's NukeIDE session | `/user/{victim}/{serverName}` | 403 via Nginx JWT proxy |
| BOLA-04 | Read another user's transactions | `GET /api/credits/transactions` | 403; admin requires `audit:read` or `system:config` |
| BOLA-05 | Modify another user's preferences | `PUT /api/users/{id}/preferences` | 403 unless self or admin with `users:update` |
| BOLA-06 | Access workspace the user is not a member of | `GET /api/workspaces/{id}` | 403 |
| BOLA-07 | Access volume not owned/shared | `GET /api/volumes/{id}` | 403 |
| BOLA-08 | Enumerate sequential server/volume/user IDs | `GET /api/servers/1`, `/api/servers/2` ... | UUIDs prevent trivial enumeration; 403 on unauthorized |

#### 4.2 Vertical Privilege Escalation (BFLA)

| ID | Test | Endpoint | Expected Result |
|----|------|----------|-----------------|
| BFLA-01 | Regular user calls admin user list | `GET /api/admin/users` | 403 |
| BFLA-02 | Regular user grants NUKE credits | `POST /api/credits/grant` | 403 |
| BFLA-03 | Regular user toggles maintenance mode | `POST /api/system/maintenance` | 403 |
| BFLA-04 | Moderator accesses user server | `/user/{user}/{server}` or admin server endpoints | 403 (moderator lacks `servers:access_all`) |
| BFLA-05 | Support deletes a user | `DELETE /api/users/{id}` | 403 (support lacks `users:delete`) |
| BFLA-06 | Mass assignment to escalate role | `PUT /api/users/{id}` with `{"role":"admin"}` | Field ignored or 403 |
| BFLA-07 | Bulk actions with low-privilege token | `POST /api/bulk/servers/bulk-action` | 403 |
| BFLA-08 | Impersonation restricted to super_admin | `POST /api/users/{id}/impersonate` | 403 for non-super_admin |

### 5.5 Phase 5 — Input Validation & Injection Testing

| ID | Test | Target | Expected Result |
|----|------|--------|-----------------|
| INJ-01 | SQL injection in API parameters | All query/path/body params | SQLAlchemy ORM; no dynamic SQL; no error leakage |
| INJ-02 | NoSQL injection | JSON body fields | No MongoDB; PostgreSQL only |
| INJ-03 | Command injection in server spawn | `POST /api/servers` | Docker SDK used directly; no shell interpolation |
| INJ-04 | Path traversal in file/avatar endpoints | `/api/users/{id}/avatar`, file browser | `secure_path()` validation; 400 on traversal |
| INJ-05 | SSRF via URL parameters | Webhook URLs, avatar imports, environment fetch | No user-controlled outbound URLs; admin-configured only |
| INJ-06 | XXE via XML upload | Any XML-consuming endpoint | No XML parsers or disabled external entities |
| INJ-07 | SSTI in environment templates | `backend/app/services/environment_service.py` | Templates stored as data; not rendered as Jinja |
| INJ-08 | Reflected/stored XSS | All user-controlled output | React auto-escaping + CSP blocks inline scripts |
| INJ-09 | HTML injection in notifications | Notification messages | Output encoded; no raw HTML from users |
| INJ-10 | JSON injection / prototype pollution | Frontend state stores | Immutable updates; no `__proto__` merging |
| INJ-11 | Host header injection | Password reset, absolute URL generation | Trusted proxy config; host validated |
| INJ-12 | HTTP parameter pollution | Repeated query/body params | Last or first value deterministically chosen |

### 5.6 Phase 6 — Business Logic Testing

| ID | Test | Flow | Expected Result |
|----|------|------|-----------------|
| LOGIC-01 | Negative NUKE balance bypass | Start server with 0 credits | Rejected with `402 Payment Required` or 422 |
| LOGIC-02 | Double-spend credits via race condition | Rapid concurrent spawn/start requests | Atomic balance check; no negative balance |
| LOGIC-03 | Quota bypass via plan/custom resource manipulation | `POST /api/servers` with oversized resources | Enforced against plan + user quota |
| LOGIC-04 | Idle timeout / max runtime bypass | WebSocket activity spoofing | Server still stopped by Celery task at deadline |
| LOGIC-05 | Schedule execution privilege escalation | Cron schedule action on another user's server | 403 unless admin |
| LOGIC-06 | Bulk operation cross-user impact | Select own server + victim server in bulk | Only authorized servers affected; 403 otherwise |
| LOGIC-07 | Workspace invitation abuse | Invite to workspace then escalate permissions | Member cannot grant permissions they don't hold |
| LOGIC-08 | Volume quota double-counting regression | Create volume + server with same disk | No double-counting (previously fixed) |
| LOGIC-09 | Maintenance mode bypass | Direct API call while maintenance enabled | 503 except exempt paths |
| LOGIC-10 | Rate-limit tier bypass | Spoof role claim in JWT | Signature invalidates tampered claims |
| LOGIC-11 | API token used for high-impact admin ops | Bulk actions with scoped token | Rejected; JWT session required |
| LOGIC-12 | Self-block prevention bypass | Admin adds own IP to blocklist | UI/API prevents self-lockout |

### 5.7 Phase 7 — Container & Infrastructure Testing

| ID | Test | Method | Expected Result |
|----|------|--------|-----------------|
| CONT-01 | Container escape via privileged flag | Inspect `docker inspect <user-container>` | `Privileged: false` |
| CONT-02 | Host path mount abuse | Inspect container mounts | Only intended named volumes; no `/var/run/docker.sock` |
| CONT-03 | Capability enumeration | `capsh --print` inside container | `CAP_DROP ALL`; minimal add if any |
| CONT-04 | User identity inside container | `id` inside NukeIDE | Non-root user (e.g., `uid=1000`) |
| CONT-05 | Read-only root filesystem | `touch /tmp/test` vs `touch /bin/test` | Root fs read-only; writable only allowed paths |
| CONT-06 | Network segmentation | Nmap scan from user container to backend/Redis/Postgres | Isolated user network; no reachability |
| CONT-07 | Docker socket access | `ls /var/run/docker.sock` inside container | Not mounted |
| CONT-08 | Container-to-container traffic | Curl from user A container to user B container | Blocked by network policy/isolation |
| CONT-09 | Metadata service access from container | `curl 169.254.169.254` | Blocked (cloud-specific if applicable) |
| CONT-10 | Image vulnerability scan | Trivy/Grype on `backend`, `frontend`, `auth-sidecar`, environment images | No critical/high CVEs in production images |
| CONT-11 | Secret exposure in image layers | `dive` / `trivy fs --scanners secret` | No hardcoded secrets in layers |
| CONT-12 | Runtime security event detection | Falco/Tetragon or manual syscall monitoring | Alerts on suspicious syscalls, file writes, network connects |

### 5.8 Phase 8 — CI/CD & Supply-Chain Review

| ID | Test | Target | Expected Result |
|----|------|--------|-----------------|
| CICD-01 | Dependency vulnerability scanning | `./nukelabctl security` | `pip-audit` and `npm audit` pass; no ignored criticals |
| CICD-02 | Container image scanning in CI | `.github/workflows/security.yml` | Trivy/Grype gate on backend/frontend/env images |
| CICD-03 | Secret scanning in repository | Gitleaks/TruffleHog scan | No active secrets in git history |
| CICD-04 | Signed commits / artifact signing | Git config, GHCR images | Commits signed; images signed with Cosign (target state). Implemented: signed-commits check warns until enforced; Cosign signing workflow in `.github/workflows/security.yml` |
| CICD-04a | Git commit signing verification | `.github/workflows/security.yml` | CI runs `./nukelabctl security --signed-commits` on every push/PR; warns during transition, fails once branch protection requires signed commits |
| CICD-04b | Container image signing with Cosign | `.github/workflows/security.yml` | Built backend/frontend/auth-sidecar images are signed with Cosign keyless signing using GitHub OIDC; signatures published to GHCR |
| CICD-04c | Cosign signature verification | `.github/workflows/security.yml` / downstream consumers | Published image signatures can be verified with `cosign verify --certificate-identity-regexp` and policy enforced in deployment workflows |
| CICD-05 | Workflow permissions | `.github/workflows/*.yml` | Minimal `permissions`, no `pull_request_target` abuse |
| CICD-06 | Base image pinning | Dockerfiles | All external base images pinned by digest; verified by `./nukelabctl security --check-base-images` |
| CICD-07 | SBOM generation | CI artifacts | CycloneDX/SPDX SBOM produced per release |

### 5.9 Phase 9 — WebSocket & Real-Time Channel Testing

| ID | Test | Target | Expected Result |
|----|------|--------|-----------------|
| WS-01 | Unauthenticated WebSocket connection | `wss://host/api/ws` | Connection rejected |
| WS-02 | Subscribe to unauthorized server metrics | Send `subscribe` for victim server ID | Rejected or no data delivered |
| WS-03 | Message flooding | Send >120 msg/min | Rate-limited / disconnected |
| WS-04 | Cross-origin WebSocket | Connect from `evil.com` | Origin validation blocks |
| WS-05 | Injection via WebSocket message | Malformed JSON / large payload | Parsed safely; no crash or code execution |

---

## 6. Tools

### 6.1 Manual Testing

| Category | Tools |
|----------|-------|
| Proxy / Repeater | Burp Suite Professional, OWASP ZAP |
| API Testing | Postman, Insomnia, httpie, curl |
| Fuzzing | ffuf, Kiterunner, wfuzz |
| JWT Analysis | jwt_tool, jwt.io, hashcat (`-m 16500`) |
| SQL Injection | sqlmap (confirmation only) |
| XSS | Dalfox, manual payloads |
| Network | nmap, masscan, Wireshark |

### 6.2 Automated Scanning

| Tool | Purpose |
|------|---------|
| OWASP ZAP | Baseline and full scan of SPA + API |
| Nuclei | CVE and misconfiguration templates |
| Nikto | Web server misconfiguration scan |
| Trivy | Container image, filesystem, IaC, secret scanning |
| Grype | Container image vulnerability scan (secondary) |
| pip-audit / npm audit | Dependency CVE scanning |
| Bandit | Python SAST |
| Semgrep | Custom SAST rules |
| Gitleaks / TruffleHog | Secret detection in repo history |
| docker-bench-security | Host/container daemon hardening |
| kube-bench / Falco | Runtime security (if K8s deployed) |

### 6.3 Custom NukeLab Test Scripts

The following scripts should be created as part of the engagement to enable repeatable retests:

- `backend/tests/security/test_bola.py` — automated BOLA sweeps across server/volume/workspace/credit endpoints.
- `backend/tests/security/test_bfla.py` — privilege-escalation matrix across all roles.
- `backend/tests/security/test_auth_tokens.py` — JWT manipulation and token-scope abuse.
- `backend/tests/security/test_credit_race.py` — concurrent credit/spawn race tests.
- `backend/tests/security/test_container_isolation.py` — runtime container escape/isolation checks.
- `scripts/run-pentest-scans.sh` — orchestrates Trivy, ZAP, Nuclei, and custom pytest suites. Implemented.
- `frontend/e2e/security/*.spec.ts` — Playwright tests for CSRF, XSS, and role-based UI hiding. Implemented (`frontend/e2e/security/frontend-security.spec.ts`).

---

## 7. Engagement Timeline

| Week | Activities | Deliverable |
|------|------------|-------------|
| **Week 1** | Kickoff, scope confirmation, account provisioning, reconnaissance, environment setup | Recon report, target inventory |
| **Week 2** | White-box architecture review, configuration audit, SAST/dependency scans | Configuration review memo |
| **Week 3** | Authentication, session, CSRF, and authorization testing (BOLA/BFLA) | Auth/authz findings draft |
| **Week 4** | Injection testing, input validation, XSS, business logic, credit/quota abuse | Injection + logic findings draft |
| **Week 5** | Container runtime testing, infrastructure/network segmentation, CI/CD review | Infra findings draft |
| **Week 6** | WebSocket testing, automated scanner correlation, evidence consolidation | Consolidated findings |
| **Week 7** | Draft report, internal peer review, walkthrough with NukeLab team | Draft penetration test report |
| **Week 8** | Remediation support, retest of fixed findings | Final report + retest memo |

---

## 8. Rules of Engagement

1. **Authorization:** Testing is authorized only against the named staging/pre-production environment. Production is out of scope unless explicitly added in writing.
2. **Business Hours:** Automated high-volume scanning is restricted to agreed windows to avoid disrupting shared environments.
3. **Data Handling:** Any PII or credentials discovered must be encrypted, reported immediately, and not retained beyond the report delivery date.
4. **Denial of Service:** DoS-style tests must be pre-approved and time-boxed. Avoid resource exhaustion of the Docker daemon.
5. **Container Safety:** Container escape tests must be run in an isolated test host or VM to prevent host compromise.
6. **Coordination:** Critical findings are reported within 24 hours of discovery; all others at the weekly checkpoint.
7. **Evidence:** All findings require reproducible steps, HTTP request/response pairs, screenshots, and CVSS 4.0 scores.

---

## 9. Deliverables

### 9.1 Executive Report

- Executive summary in business terms.
- Risk matrix by severity and OWASP category.
- Attack narrative highlighting worst-case impact.
- Remediation roadmap with effort estimates.
- Statement of testing scope and limitations.

### 9.2 Technical Report

For each finding:

- **Finding ID** (e.g., `PENT-NKL-001`)
- **Title**
- **Severity** (CVSS 4.0 base + environmental)
- **OWASP Category** (Web / API / Container)
- **Affected URL/Component**
- **Description**
- **Prerequisites / Conditions**
- **Reproduction Steps** (step-by-step)
- **Evidence** (requests, responses, screenshots, commands)
- **Impact**
- **Remediation** (code-level guidance)
- **Retest Criteria**
- **References**

### 9.3 Supplementary Artifacts

- `PENETRATION-TEST-FINDINGS.md` — tracked list with status (Open / In Progress / Retested / Closed).
- `PENETRATION-TEST-REMEDIATION.md` — owner-assigned remediation tracker.
- `backend/reports/security/pentest/` — raw tool outputs (ZAP XML, Nuclei JSON, Trivy SARIF).
- `scripts/run-pentest-scans.sh` — repeatable scan runner.
- `backend/tests/security/` — pytest regression suite.

---

## 10. Severity Rating

Use CVSS 4.0 with the following mapping:

| CVSS 4.0 Score | Severity | Action Required |
|----------------|----------|-----------------|
| 9.0–10.0 | Critical | Fix before go-live; emergency patch process |
| 7.0–8.9 | High | Fix before go-live; management exception required |
| 4.0–6.9 | Medium | Fix within 30 days of report |
| 0.1–3.9 | Low | Fix within 90 days or accept risk |
| 0.0 | Informational | Documented, no immediate action |

---

## 11. Retest & Acceptance

1. NukeLab team remediates findings and provides evidence (commit hashes, test results).
2. Tester verifies each fix against the documented retest criteria.
3. Retested findings are updated in `PENETRATION-TEST-FINDINGS.md`.
4. A signed retest memo is appended to the final report.
5. Go-live requires:
   - Zero critical/high findings.
   - All medium findings either fixed or accepted by the security lead.
   - Regression tests in `backend/tests/security/` passing in CI.

---

## 12. Mapping to Existing NukeLab Controls

| OWASP / Control | Implemented Evidence | Test Focus |
|-------------------|----------------------|------------|
| RBAC | `backend/app/core/roles.py` | Verify no bypass via token claims or parameter tampering |
| Rate Limiting | `backend/app/middleware/rate_limit.py` | Confirm tier enforcement and bypass resistance |
| CSRF | `backend/app/middleware/csrf.py` | Validate double-submit on all state-changing routes |
| Security Headers | `backend/app/core/security_headers_asgi.py` | Confirm headers on 200/400/500 responses |
| Path Traversal | `backend/app/core/security.py::secure_path()` | Test traversal in file endpoints |
| Container Security | `backend/app/container/spawner.py` | Verify non-root, capability drop, no docker socket |
| Audit Logging | `backend/app/middleware/audit.py` | Confirm all privilege tests are logged |
| Credit System | `backend/app/services/credit_service.py` | Race-condition and logic-abuse tests |
| CORS | `backend/app/middleware/cors.py` / config | Verify production origin whitelist |
| IP Restrictions | `backend/app/middleware/ip_restriction.py` | Test CIDR matching and self-block prevention |

---

## 13. Glossary

| Term | Definition |
|------|------------|
| **BOLA** | Broken Object Level Authorization (OWASP API1:2023) |
| **BFLA** | Broken Function Level Authorization (OWASP API5:2023) |
| **NukeIDE** | Theia-based IDE running inside user containers |
| **NUKE** | Platform credit currency for resource billing |
| **PTES** | Penetration Testing Execution Standard |
| **WSTG** | OWASP Web Security Testing Guide |

---

## 14. Next Steps

1. **Approve scope and timeline** with stakeholders.
2. **Provision test accounts** and a dedicated staging/pre-production environment.
3. **Freeze major code changes** during active testing weeks where possible.
4. **Assign a security liaison** from the NukeLab team for daily triage.
5. **Run `./nukelabctl security` baseline** before testing begins to capture pre-engagement state.
6. **Begin Phase 1 reconnaissance** once the engagement is authorized.

---

**Prepared for:** NukeLab Security Review  
**Prepared by:** Security Engineering  
**Date:** 2026-06-28
