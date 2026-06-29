# NukeLab Penetration Test Findings

> **Status:** Template — populate during engagement  
> **Plan:** `docs/PENETRATION-TEST-PLAN.md`  
> **Remediation tracker:** `docs/PENETRATION-TEST-REMEDIATION.md`

---

## Legend

| Status | Meaning |
|--------|---------|
| Open | Confirmed, not yet fixed |
| In Progress | Fix actively being developed |
| Retest Ready | Fix deployed, awaiting retest |
| Retested | Retest passed |
| Closed | Retested and accepted |
| Risk Accepted | Not fixed; documented risk acceptance |
| False Positive | Finding invalidated after review |

---

## Findings

| ID | Title | Severity | Category | Status | Reporter | Owner | Opened | Closed |
|----|-------|----------|----------|--------|----------|-------|--------|--------|
| PENT-NKL-001 | Container runtime runs as root | Medium | Container Security | Closed | Security Eng | Backend Eng | 2026-06-28 | 2026-06-28 |
| PENT-NKL-002 | Container runtime retains Linux capabilities | Medium | Container Security | Closed | Security Eng | Backend Eng | 2026-06-28 | 2026-06-28 |
| PENT-NKL-003 | Container root filesystem is writable | Medium | Container Security | Closed | Security Eng | Backend Eng | 2026-06-28 | 2026-06-28 |
| PENT-NKL-004 | NoNewPrivileges not enforced on containers | Medium | Container Security | Closed | Security Eng | Backend Eng | 2026-06-28 | 2026-06-28 |
| PENT-NKL-005 | python-socketio DoS via withheld binary attachments | High | Supply Chain / Dependency | Closed | Security Eng | Backend Eng | 2026-06-28 | 2026-06-28 |
| PENT-NKL-006 | External base images not pinned by digest | Medium | Supply Chain / Dependency | Open | Security Eng | Platform Eng | 2026-06-28 | |
| PENT-NKL-007 | Commits are not cryptographically signed | Medium | Supply Chain / Source Integrity | Open | Security Eng | Platform Eng | 2026-06-28 | |
| PENT-NKL-008 | Auth sidecar ships vulnerable Go runtime and JWT library | High | Supply Chain / Dependency | Closed | Security Eng | Backend Eng | 2026-06-28 | 2026-06-28 |
| PENT-NKL-009 | Auth sidecar mounts wrong server-auth public key volume | High | Container Security / Authentication | Closed | Security Eng | Backend Eng | 2026-06-28 | 2026-06-28 |
| PENT-NKL-010 | Server gateway page reloads instead of opening terminal | Medium | Frontend Security / Cache Handling | Closed | Security Eng | Frontend Eng | 2026-06-28 | 2026-06-28 |
| PENT-NKL-011 | Backend reports server running before container is ready | Medium | Backend / Container Orchestration | Closed | Security Eng | Backend Eng | 2026-06-28 | 2026-06-28 |

---

## Finding Detail Template

### PENT-NKL-XXX: Title

**Severity:** Critical / High / Medium / Low / Informational  
**CVSS 4.0 Score:** X.X  
**OWASP Category:** e.g., API1:2023 BOLA, A01:2021 Broken Access Control  
**Status:** Open  
**Opened:** YYYY-MM-DD  
**Reporter:** Name  
**Owner:** Name  
**Component:** e.g., `backend/app/api/servers.py`  

**Description:**
Brief description of the vulnerability.

**Prerequisites:**
- Authenticated user with role `user`
- Target server ID belonging to another user

**Reproduction Steps:**
1. Authenticate as User A.
2. Capture request `GET /api/servers/{victim_server_id}`.
3. Observe 200 with victim server details.

**Evidence:**
```http
GET /api/servers/550e8400-e29b-41d4-a716-446655440001 HTTP/1.1
Host: staging.nukelab.example.com
Authorization: Bearer <User_A_token>
```

**Impact:**
What can an attacker achieve?

**Remediation:**
Specific code-level or config fix.

**Retest Criteria:**
- `GET /api/servers/{other_user_server_id}` returns 403 for non-authorized users.
- Regression test `backend/tests/security/test_bola.py::test_server_bola` passes.

**References:**
- OWASP API1:2023 Broken Object Level Authorization
- Internal control: `backend/app/core/roles.py`

---

## Statistics

| Severity | Open | In Progress | Retest Ready | Retested | Closed | Risk Accepted |
|----------|------|-------------|--------------|----------|--------|---------------|
| Critical | 0 | 0 | 0 | 0 | 0 | 0 |
| High | 0 | 0 | 0 | 0 | 2 | 0 |
| Medium | 2 | 0 | 0 | 0 | 5 | 0 |
| Low | 0 | 0 | 0 | 0 | 0 | 0 |
| Informational | 0 | 0 | 0 | 0 | 0 | 0 |

---

## Finding Details

### PENT-NKL-001: Container runtime runs as root

**Severity:** Medium  
**CVSS 4.0 Score:** 6.9  
**OWASP Category:** A05:2021 Security Misconfiguration  
**Status:** Closed  
**Opened:** 2026-06-28  
**Closed:** 2026-06-28  
**Reporter:** Security Eng  
**Owner:** Backend Eng  
**Component:** `backend/app/container/spawner.py`, `backend/app/container/client.py`, `environments/base/Dockerfile`, `environments/dev/Dockerfile`

**Description:**
User-facing server containers are spawned without an explicit non-root `User` directive. If the underlying image defaults to `root`, any container compromise gives the attacker root privileges inside the container, easing privilege escalation to the host.

**Evidence:**
- Regression test `test_container_runs_as_non_root` passes.
- `ContainerClient.create_container` sets both `HostConfig["User"]` and `Config["User"] = "65532:65532"` when `container_hardening_enabled` is true.
- `environments/base/Dockerfile` pre-creates the `nukelab` user/group with uid/gid 65532.
- `environments/dev/Dockerfile` and `environments/dev/start.sh` support starting as the non-root user.
- Live retest (2026-06-28): spawned `hardened-retest-a` via the API; `podman inspect` shows `Config.User=65532:65532` and `id` inside the container reports `uid=65532(nukelab)`.

**Impact:**
A vulnerability in a user workload (e.g., RCE via uploaded notebook) executes as root, increasing blast radius and simplifying container-escape exploits.

**Remediation:**
Set `config["User"]` in `create_container`, create a matching user inside environment images, and ensure `/home/{username}` is owned by that user. The dev image now runs nginx on unprivileged port 8080 and starts services as the container user.

**Retest Criteria:**
- `test_container_runs_as_non_root` passes.
- `./nukelabctl verify-hardening <container>` passes.
- Container inspection shows `Config.User` is non-empty and not `root`/`0`.
- Live spawn of a dev server completes successfully with `container_hardening_enabled=true`.

**References:**
- CIS Docker Benchmark v1.8.0, section 4.1
- OWASP Top 10 2021 A05

---

### PENT-NKL-002: Container runtime retains Linux capabilities

**Severity:** Medium  
**CVSS 4.0 Score:** 6.5  
**OWASP Category:** A05:2021 Security Misconfiguration  
**Status:** Closed  
**Opened:** 2026-06-28  
**Closed:** 2026-06-28  
**Reporter:** Security Eng  
**Owner:** Backend Eng  
**Component:** `backend/app/container/client.py`

**Description:**
Containers are started without dropping Linux capabilities. Unneeded capabilities such as `CAP_SYS_ADMIN`, `CAP_NET_ADMIN`, or `CAP_SYS_PTRACE` may be inherited from the container runtime defaults.

**Evidence:**
- Regression test `test_container_drops_all_capabilities` passes.
- `ContainerClient.create_container` adds `"CapDrop": ["ALL"]` to `HostConfig` when hardening is enabled.
- Live retest (2026-06-28): `podman inspect` shows `HostConfig.CapDrop=[CAP_CHOWN ... CAP_SYS_CHROOT]` and `/proc/self/status` inside the container reports all capability sets as `0000000000000000`.

**Impact:**
Retained capabilities broaden the kernel attack surface and can be combined with other weaknesses to escape the container.

**Remediation:**
Add `"CapDrop": ["ALL"]` to `HostConfig` and explicitly allow only the minimal set required. This is now implemented behind `container_drop_all_capabilities`.

**Retest Criteria:**
- `test_container_drops_all_capabilities` passes.
- `./nukelabctl verify-hardening <container>` passes.
- `docker inspect` shows `"CapDrop": ["ALL"]` and no unexpected `CapAdd` entries.

**References:**
- CIS Docker Benchmark v1.8.0, section 4.4
- OWASP Top 10 2021 A05

---

### PENT-NKL-003: Container root filesystem is writable

**Severity:** Medium  
**CVSS 4.0 Score:** 6.1  
**OWASP Category:** A05:2021 Security Misconfiguration  
**Status:** Closed  
**Opened:** 2026-06-28  
**Closed:** 2026-06-28  
**Reporter:** Security Eng  
**Owner:** Backend Eng  
**Component:** `backend/app/container/client.py`, `environments/dev/nginx.conf`, `environments/dev/start.sh`

**Description:**
Containers are started with a writable root filesystem. Malware or accidental writes can modify system binaries, install persistence, or corrupt the image.

**Evidence:**
- Regression test `test_container_has_read_only_root_filesystem` passes.
- `ContainerClient.create_container` sets `"ReadonlyRootfs": True` and mounts writable tmpfs on `/tmp`, `/var/tmp`, `/var/run`, `/var/log/nginx`, and `/var/cache/nginx` when hardening is enabled.
- `environments/dev/nginx.conf` logs to stderr and uses tmpfs-backed temp paths.
- Live retest (2026-06-28): `podman inspect` shows `HostConfig.ReadonlyRootfs=true`; `touch /etc/testfile` inside the container fails with a read-only filesystem, while `touch /home/nukelab/testfile` succeeds.

**Impact:**
A writable rootfs enables in-container persistence and makes it harder to reason about container integrity. Combined with a writable `/tmp`, it supports malware staging.

**Remediation:**
Set `"ReadonlyRootfs": True` in `HostConfig`. Mount writable tmpfs on `/tmp`, `/var/tmp`, and any application-specific write paths. Ensure logs are written to a volume or stdout.

**Retest Criteria:**
- `test_container_has_read_only_root_filesystem` passes.
- `./nukelabctl verify-hardening <container>` passes.
- `docker inspect` shows `"ReadonlyRootfs": true`.
- User workloads can still write to `/home/{username}`.

**References:**
- CIS Docker Benchmark v1.8.0, section 4.6
- OWASP Top 10 2021 A05

---

### PENT-NKL-004: NoNewPrivileges not enforced on containers

**Severity:** Medium  
**CVSS 4.0 Score:** 6.1  
**OWASP Category:** A05:2021 Security Misconfiguration  
**Status:** Closed  
**Opened:** 2026-06-28  
**Closed:** 2026-06-28  
**Reporter:** Security Eng  
**Owner:** Backend Eng  
**Component:** `backend/app/container/client.py`

**Description:**
Containers are started without `NoNewPrivileges`, allowing processes inside the container to gain additional privileges via setuid binaries.

**Evidence:**
- Regression test `test_container_has_no_new_privileges` passes.
- `ContainerClient.create_container` adds `"SecurityOpt": ["no-new-privileges:true"]` to `HostConfig` when hardening is enabled.
- Live retest (2026-06-28): `podman inspect` shows `HostConfig.SecurityOpt=[no-new-privileges]`.

**Impact:**
An attacker who compromises a container process can exploit setuid binaries to escalate privileges within the container.

**Remediation:**
Add `"SecurityOpt": ["no-new-privileges:true"]` to `HostConfig` in `create_container`.

**Retest Criteria:**
- `test_container_has_no_new_privileges` passes.
- `./nukelabctl verify-hardening <container>` passes.
- `docker inspect` shows `"SecurityOpt": ["no-new-privileges:true"]`.

**References:**
- CIS Docker Benchmark v1.8.0, section 4.5
- OWASP Top 10 2021 A05

---

### PENT-NKL-005: python-socketio DoS via withheld binary attachments

**Severity:** High  
**CVSS 4.0 Score:** 7.1  
**OWASP Category:** A06:2021 Vulnerable and Outdated Components  
**Status:** Closed  
**Opened:** 2026-06-28  
**Closed:** 2026-06-28  
**Reporter:** Security Eng  
**Owner:** Backend Eng  
**Component:** `backend/requirements.txt`, `backend/app/websocket/metrics_socket.py`

**Description:**
The installed `python-socketio` package version 5.14.0 was affected by GHSA-5w7q-77mv-v69f / CVE-2026-48804. An unauthenticated or authenticated WebSocket client could submit a binary `EVENT` or `ACK` message and intentionally withhold one or more attachments. The server kept the partial message in memory while waiting for the missing attachments, allowing memory exhaustion and denial of service.

**Evidence:**
- `backend/requirements.txt` now pins `python-socketio==5.16.2`.
- `./nukelabctl security` / `pip-audit` no longer reports a `python-socketio` vulnerability.

**Impact:**
A remote attacker could exhaust server memory by opening many Socket.IO connections and sending binary events without completing attachments. This could degrade or crash the WebSocket/metrics service for all users.

**Remediation:**
Upgraded `python-socketio` to `>=5.16.2` in `backend/requirements.txt` and rebuilt container images.

**Retest Criteria:**
- `pip-audit` no longer reports `python-socketio` as vulnerable.
- `./nukelabctl security` exits without pip-audit findings.
- WebSocket regression tests (`backend/tests/security/test_websocket.py`) still pass.

**References:**
- GHSA-5w7q-77mv-v69f
- CVE-2026-48804
- OWASP Top 10 2021 A06

---

### PENT-NKL-006: External base images not pinned by digest

**Severity:** Medium  
**CVSS 4.0 Score:** 5.5  
**OWASP Category:** A06:2021 Vulnerable and Outdated Components / Supply Chain  
**Status:** Open  
**Opened:** 2026-06-28  
**Reporter:** Security Eng  
**Owner:** Platform Eng  
**Component:** `backend/Dockerfile`, `frontend/Dockerfile`, `environments/base/Dockerfile`, `services/auth-sidecar/Dockerfile`

**Description:**
External base images are referenced by floating tags instead of by digest. A malicious or compromised registry can serve a different image than the one originally tested, introducing vulnerabilities or backdoors into the build pipeline.

**Evidence:**
- `./scripts/security/check-base-image-pinning.sh --strict` reports 5 unpinned external base images:
  - `python:3.12-slim`
  - `ubuntu:24.04`
  - `node:22-alpine`
  - `docker.io/library/nginx:alpine`
  - `golang:1.25-alpine`
- Internal multi-stage aliases (`base`) and internal `nukelab-*` images are correctly skipped.

**Impact:**
Build reproducibility and supply-chain integrity are weakened. A tag rollback or registry compromise can silently change the contents of production images.

**Remediation:**
Pin each external base image by digest (e.g., `ubuntu:24.04@sha256:<digest>`) and update via an automated dependency update workflow. Alternatively, mirror images to an internal registry and pin to mirrored digests.

**Retest Criteria:**
- `./nukelabctl security --check-base-images` passes with no unpinned external images.
- Any exceptions are documented in an explicit allowlist.

**References:**
- OWASP Top 10 2021 A06
- SLSA Supply-chain Levels for Software Artifacts

---

### PENT-NKL-007: Commits are not cryptographically signed

**Severity:** Medium  
**CVSS 4.0 Score:** 5.3  
**OWASP Category:** A05:2021 Security Misconfiguration / Source Integrity  
**Status:** Open  
**Opened:** 2026-06-28  
**Reporter:** Security Eng  
**Owner:** Platform Eng  
**Component:** Git repository

**Description:**
The repository history does not require or verify cryptographically signed commits. An attacker who compromises a developer account or CI credential can push malicious code that appears legitimate in the commit log.

**Evidence:**
- `./scripts/security/check-signed-commits.sh --strict` reports 339 unsigned commits on the current branch.
- No branch protection rule enforces signed commits.

**Impact:**
Reduced confidence in source provenance. Malicious commits are harder to detect and attribute.

**Remediation:**
1. Configure commit signing for all maintainers (GPG, SSH, or S/MIME).
2. Enable "Require signed commits" on protected branches.
3. Optionally add a CI gate that fails the build if unsigned commits are present.

**Retest Criteria:**
- `./nukelabctl security --signed-commits` passes.
- Branch protection requires signed commits.

**References:**
- GitHub Docs: Managing commit signature verification
- OWASP Top 10 2021 A05

---

### PENT-NKL-008: Auth sidecar ships vulnerable Go runtime and JWT library

**Severity:** High  
**CVSS 4.0 Score:** 7.5  
**OWASP Category:** A06:2021 Vulnerable and Outdated Components  
**Status:** Closed  
**Opened:** 2026-06-28  
**Closed:** 2026-06-28  
**Reporter:** Security Eng  
**Owner:** Backend Eng  
**Component:** `services/auth-sidecar/Dockerfile`, `services/auth-sidecar/go.mod`

**Description:**
The auth-sidecar image was built on Go 1.21.13 and `github.com/golang-jwt/jwt/v5` v5.2.0. Trivy identified multiple HIGH and CRITICAL vulnerabilities in the Go standard library (CVE-2024-34156, CVE-2025-61726, CVE-2025-61729, CVE-2025-68121, CVE-2026-25679, CVE-2026-32280, CVE-2026-32281, CVE-2026-32283, CVE-2026-33811, CVE-2026-33814, CVE-2026-39820, CVE-2026-39836, CVE-2026-42499) and HIGH CVE-2025-30204 in the JWT library.

**Evidence:**
- Initial Trivy image scan of `nukelab-auth-sidecar:latest` reported 14 HIGH/CRITICAL Go stdlib findings and one HIGH JWT finding.
- `services/auth-sidecar/Dockerfile` builder stage updated from `golang:1.21-alpine` to `golang:1.25-alpine`.
- `services/auth-sidecar/go.mod` updated to `go 1.24` and `github.com/golang-jwt/jwt/v5 v5.2.2`.
- Rebuilt `nukelab-auth-sidecar:latest`; subsequent Trivy scan reports 0 HIGH/CRITICAL findings.
- `./nukelabctl security` completes with no blocking findings.

**Impact:**
Outdated dependencies in a security-critical sidecar could allow denial of service, incorrect certificate validation, or JWT verification bypass, undermining authentication controls.

**Remediation:**
Upgrade the Go toolchain to a supported release (1.25.x) and the JWT library to the latest patched version (v5.2.2). Rebuild and re-scan the image before deployment.

**Retest Criteria:**
- `trivy image --severity HIGH,CRITICAL nukelab-auth-sidecar:latest` reports zero findings.
- `./nukelabctl security` passes.

**References:**
- CVE-2025-30204
- CVE-2025-68121
- OWASP Top 10 2021 A06

---

### PENT-NKL-009: Auth sidecar mounts wrong server-auth public key volume

**Severity:** High
**CVSS 4.0 Score:** 7.1
**OWASP Category:** A07:2021 Identification and Authentication Failures
**Status:** Closed
**Opened:** 2026-06-28
**Closed:** 2026-06-28
**Reporter:** Security Eng
**Owner:** Backend Eng
**Component:** `backend/app/container/spawner.py`

**Description:**
The server spawner mounted the `nukelab-secrets` named volume at `/etc/nukelab/auth` inside spawned containers, while the backend signs server access tokens with the private key stored in the `nukelab-server-secrets` volume. Because the auth-sidecar received a stale or mismatched public key, it could not validate legitimately issued server access tokens. This caused `401 Unauthorized` responses when users attempted to open a server terminal through the reverse proxy.

**Evidence:**
- Server access tokens signed by the backend (`RS256`) were rejected by the auth-sidecar with `crypto/rsa: verification error`.
- `podman inspect` on affected containers showed `/etc/nukelab/auth` mounted from `nukelab-secrets` instead of `nukelab-server-secrets`.
- `backend/app/container/spawner.py` was updated to mount `nukelab-server-secrets` at `/etc/nukelab/auth` in read-only mode.
- `backend/tests/container/test_spawner.py` assertions were updated to expect `nukelab-server-secrets`.
- After rebuilding the backend image and spawning a fresh server (`auth-fix-e2e-03`), the auth-sidecar loaded the correct public key, token validation succeeded, and the ttyd terminal page was served successfully.

**Impact:**
Authenticated users could be denied access to their own servers, and the auth-sidecar's local token validation would fail open to 401, breaking the terminal feature and undermining confidence in the server access control boundary.

**Remediation:**
Mount the same named volume the backend uses for server-auth keys (`nukelab-server-secrets`) into spawned containers at `/etc/nukelab/auth` so the public key matches the private key used to sign tokens.

**Retest Criteria:**
- Spawn a fresh server through the API/UI.
- `./nukelabctl verify-hardening <container_name>` passes.
- Generate a server access token and request the server's external URL; response must be the ttyd terminal HTML (HTTP 200), not `401 Unauthorized`.
- Auth-sidecar logs must not show `token signature is invalid` for valid tokens.

**References:**
- `docs/USER-AUTH-KEYS.md`
- OWASP Top 10 2021 A07

---

### PENT-NKL-010: Server gateway page reloads instead of opening terminal

**Severity:** Medium  
**CVSS 4.0 Score:** 5.3  
**OWASP Category:** A05:2021 Security Misconfiguration  
**Status:** Closed  
**Opened:** 2026-06-28  
**Closed:** 2026-06-28  
**Reporter:** Security Eng  
**Owner:** Frontend Eng  
**Component:** `frontend/src/routes/user.$username.$serverName.tsx`, `frontend/public/sw.js`, `frontend/public/sw.js.tpl`

**Description:**
When a server reached the `running` state, the gateway page at `/user/{username}/{serverName}` attempted to open the terminal by assigning the current URL to `window.location.href`. Because the terminal shares the same path as the gateway page, this caused the React app shell to reload instead of navigating to the server container. Additionally, the service worker intercepted `/user/` navigation requests and cached the gateway HTML as `/index.html`, which could return the gateway page for subsequent app navigations.

**Evidence:**
- `frontend/src/routes/user.$username.$serverName.tsx` previously used `window.location.href = targetUrl` in both the auto-redirect `useEffect` and `handleManualOpen`.
- Other server list pages (`servers.$serverId.tsx`, `servers.index.tsx`, `admin.servers.tsx`) already opened the server URL in a new tab with `window.open(..., '_blank', 'noopener,noreferrer')`.
- Direct curl to the server URL with a valid access token returned the ttyd terminal HTML, proving Traefik → container → auth-sidecar routing was correct and the issue was purely the frontend navigation mechanism.
- `frontend/public/sw.js` and `frontend/public/sw.js.tpl` now include `/user/` in `BYPASS_PATHS`, so service workers do not intercept terminal-bound navigation requests or cache them as the app shell.

**Impact:**
Users could not open a running server terminal from the gateway page, breaking the core server-access workflow. The service worker also risked caching server responses as the app shell, polluting the offline cache.

**Remediation:**
- Change the gateway page's manual "Open Environment" handler to `window.open(targetUrl, '_blank', 'noopener,noreferrer')`, consistent with other server pages.
- Add `/user/` to the service worker `BYPASS_PATHS` so terminal routes are always fetched directly from the network and never cached as `/index.html`.

**Retest Criteria:**
- Start a server and navigate to its gateway page.
- Click "Open Environment"; a new tab must open to the server terminal (ttyd) without reloading the gateway page.
- Verify `sw.js` contains `/user/` in `BYPASS_PATHS`.
- Verify no `/user/` response is stored in the browser's `nukelab-*` service worker cache as `/index.html`.

**References:**
- OWASP Top 10 2021 A05
- Service Worker caching best practices

---

### PENT-NKL-011: Backend reports server running before container is ready

**Severity:** Medium  
**CVSS 4.0 Score:** 5.3  
**OWASP Category:** A05:2021 Security Misconfiguration  
**Status:** Closed  
**Opened:** 2026-06-28  
**Closed:** 2026-06-28  
**Reporter:** Security Eng  
**Owner:** Backend Eng  
**Component:** `backend/app/container/spawner.py`, `backend/app/container/client.py`, `backend/app/config.py`

**Description:**
The backend marked a server as `running` immediately after the Docker/Podman container process started, without waiting for the server process (ttyd + auth-sidecar + nginx) to be reachable. This created a race condition where the UI showed a running server but direct access returned `502 Bad Gateway` or `401 Unauthorized` for 10–20 seconds while internal services initialized.

**Evidence:**
- `backend/app/container/spawner.py` previously returned as soon as `client.start_container()` completed.
- Server containers need several seconds for the auth-sidecar to start validating tokens and for nginx/ttyd to expose `/health`.
- Backend logs now show `Waiting up to 60s for container <name> to become ready at http://<name>:8080/health` followed by `Container <name> is ready` before the API returns `running`.
- Direct curl to the server URL immediately after the API returns `running` now returns HTTP 200 with ttyd HTML.

**Impact:**
Users attempting to open a server immediately after the UI indicated it was running encountered errors, degrading the core workflow and creating the appearance that access was broken or that hardening had regressed.

**Remediation:**
- Add `container_readiness_timeout` (default 60s) and `container_readiness_interval` (default 1s) to `backend/app/config.py`.
- Add `ContainerClient.wait_for_container_ready(container_name, health_url)` in `backend/app/container/client.py` that probes the container's internal `/health` endpoint over the shared container network until it responds with HTTP 200.
- Call the readiness probe from `backend/app/container/spawner.py` after `start_container()` before updating the server status to `running`.
- Add unit tests in `backend/tests/container/test_client.py` and `backend/tests/container/test_spawner.py`.

**Retest Criteria:**
- Spawn a fresh server through the API/UI.
- The backend log must contain `Container <name> is ready` before the API returns `running`.
- Immediately request the server's external URL with a valid access token; response must be HTTP 200 with ttyd terminal HTML (no 502/401).
- `./nukelabctl lint backend` and `./nukelabctl build backend` pass.
- `backend/tests/container/test_client.py::TestContainerLifecycle::test_wait_for_container_ready_succeeds`, `test_wait_for_container_ready_times_out`, and `backend/tests/container/test_spawner.py::TestSpawnSuccess::test_spawn_waits_for_container_ready` pass.

**References:**
- OWASP Top 10 2021 A05
- Container readiness probe best practices

---

**Last Updated:** 2026-06-28

**Note:** Container hardening controls (PENT-NKL-001 through PENT-NKL-004) are implemented, covered by regression tests, and verified through a live container spawn/inspection. They are marked **Closed**.
