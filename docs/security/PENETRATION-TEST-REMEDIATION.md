# NukeLab Penetration Test Remediation Tracker

> **Status:** Template — populate during engagement  
> **Plan:** `PENETRATION-TEST-PLAN.md`  
> **Findings:** `PENETRATION-TEST-FINDINGS.md`

---

## Active Remediations

| Finding ID | Title | Owner | Due Date | Status | PR / Commit | Notes |
|------------|-------|-------|----------|--------|-------------|-------|
| PENT-NKL-001 | Container runtime runs as root | Backend Eng | 2026-06-28 | Closed | `backend/app/container/client.py`, `backend/app/container/spawner.py`, `backend/app/config.py`, `environments/base/Dockerfile`, `environments/dev/Dockerfile`, `environments/base/start.sh`, `environments/base/nginx.conf`, `compose.yml`, `.env.development` | Hardening gated by `container_hardening_enabled` (default on except `dev_mode=true`, overridden to true in dev for regression testing); live retest passed |
| PENT-NKL-002 | Container runtime retains Linux capabilities | Backend Eng | 2026-06-28 | Closed | `backend/app/container/client.py`, `backend/app/config.py` | `CapDrop: ["ALL"]` applied when hardening enabled; live retest passed |
| PENT-NKL-003 | Container root filesystem is writable | Backend Eng | 2026-06-28 | Closed | `backend/app/container/client.py`, `backend/app/config.py`, `environments/base/nginx.conf` | `ReadonlyRootfs: true` with tmpfs mounts; live retest passed |
| PENT-NKL-004 | NoNewPrivileges not enforced on containers | Backend Eng | 2026-06-28 | Closed | `backend/app/container/client.py`, `backend/app/config.py` | `SecurityOpt: ["no-new-privileges:true"]` applied when hardening enabled; live retest passed |
| PENT-NKL-005 | python-socketio DoS via withheld binary attachments | Backend Eng | 2026-06-28 | Closed | `backend/requirements.txt` | Upgraded to `python-socketio==5.16.2`; `./nukelabctl security` passes |
| PENT-NKL-006 | External base images not pinned by digest | Platform Eng | 2026-06-29 | Closed | `backend/Dockerfile`, `environments/base/Dockerfile`, `environments/default/Dockerfile`, `frontend/Dockerfile`, `services/auth-sidecar/Dockerfile` | Pinned all external base images by digest; `./nukelabctl security --check-base-images` passes; `.github/workflows/security.yml` enforces pinning in CI |
| PENT-NKL-007 | Commits are not cryptographically signed | Platform Eng | 2026-07-12 | Open | `.github/workflows/security.yml` | Enable GPG or SSH commit signing for all maintainers and turn on branch-protection "Require signed commits" for `main`; CI job `signed-commits-check` is included and set to warn-only until enforcement is enabled |
| PENT-NKL-008 | Auth sidecar ships vulnerable Go runtime and JWT library | Backend Eng | 2026-06-28 | Closed | `services/auth-sidecar/Dockerfile`, `services/auth-sidecar/go.mod` | Upgraded builder to `golang:1.25-alpine` and `golang-jwt/jwt/v5` to v5.2.2; Trivy reports 0 HIGH/CRITICAL findings |
| PENT-NKL-009 | Auth sidecar mounts wrong server-auth public key volume | Backend Eng | 2026-06-28 | Closed | `backend/app/container/spawner.py`, `backend/tests/container/test_spawner.py` | Mount `nukelab-server-secrets` at `/etc/nukelab/auth`; end-to-end terminal access verified |
| PENT-NKL-010 | Server gateway page reloads instead of opening terminal | Frontend Eng | 2026-06-28 | Closed | `frontend/src/routes/user.$username.$serverName.tsx`, `frontend/public/sw.js`, `frontend/public/sw.js.tpl` | Open terminal in new tab; bypass `/user/` in service worker; frontend rebuilt and redeployed |
| PENT-NKL-011 | Backend reports server running before container is ready | Backend Eng | 2026-06-28 | Closed | `backend/app/container/spawner.py`, `backend/app/container/client.py`, `backend/app/config.py`, `backend/tests/container/test_client.py`, `backend/tests/container/test_spawner.py` | Wait for container `/health` before returning `running`; live spawn shows terminal accessible immediately after status flip |

---

## Remediation Workflow

1. **Triage:** Validate finding and assign severity/owner.
2. **Plan:** Document fix approach and regression test plan.
3. **Implement:** Create fix and regression test under `backend/tests/security/`.
4. **Review:** Peer review fix and test; run `./nukelabctl lint all` and `./nukelabctl test all`.
5. **Deploy:** Merge to main and deploy to staging.
6. **Retest:** Tester verifies against retest criteria; update `PENETRATION-TEST-FINDINGS.md`.
7. **Close:** Mark finding Closed once retest passes.

---

## Risk Acceptance Process

If a finding will not be remediated:

1. Document business justification.
2. Identify compensating controls.
3. Obtain sign-off from security lead and product owner.
4. Update finding status to **Risk Accepted** in `PENETRATION-TEST-FINDINGS.md`.
5. Schedule periodic re-evaluation.

---

## Retest Log

| Finding ID | Retest Date | Tester | Result | Evidence |
|------------|-------------|--------|--------|----------|
| PENT-NKL-005 | 2026-06-28 | Security Eng | Pass | `./nukelabctl security` reports 0 pip-audit vulnerabilities |
| PENT-NKL-001 | 2026-06-28 | Security Eng | Pass (regression + live) | `backend/tests/security/test_container_isolation.py::TestContainerHardening::test_container_runs_as_non_root` passes; live spawn `hardened-retest-a` shows `Config.User=65532:65532` |
| PENT-NKL-002 | 2026-06-28 | Security Eng | Pass (regression + live) | `backend/tests/security/test_container_isolation.py::TestContainerHardening::test_container_drops_all_capabilities` passes; live inspect shows `CapDrop=[ALL]` and `/proc/self/status` caps all zero |
| PENT-NKL-003 | 2026-06-28 | Security Eng | Pass (regression + live) | `backend/tests/security/test_container_isolation.py::TestContainerHardening::test_container_has_read_only_root_filesystem` passes; live inspect shows `ReadonlyRootfs=true`, `/etc` read-only, `/home/nukelab` writable |
| PENT-NKL-004 | 2026-06-28 | Security Eng | Pass (regression + live) | `backend/tests/security/test_container_isolation.py::TestContainerHardening::test_container_has_no_new_privileges` passes; live inspect shows `SecurityOpt=[no-new-privileges]` |
| PENT-NKL-001 through PENT-NKL-004 | 2026-06-28 | Security Eng | Pass (end-to-end) | API login → create environment (`localhost/nukelab-base:latest`) → spawn server (`hardened-retest-a`) → `podman exec` confirms non-root, no caps, read-only rootfs, no-new-privileges, and `/user/admin2/hardened-retest-a/health` returns `healthy` via Traefik |
| PENT-NKL-008 | 2026-06-28 | Security Eng | Pass | Rebuilt `nukelab-auth-sidecar:latest` on Go 1.25 with `golang-jwt/jwt/v5` v5.2.2; `trivy image --severity HIGH,CRITICAL` reports 0 findings; `./nukelabctl security` passes |
| PENT-NKL-009 | 2026-06-28 | Security Eng | Pass | Rebuilt backend image; spawned `auth-fix-e2e-03`; `./nukelabctl verify-hardening` passed; server access token loaded terminal URL (ttyd HTML) with no 401; auth-sidecar logs show no signature errors |
| PENT-NKL-010 | 2026-06-28 | Security Eng | Pass | Rebuilt frontend image; verified `sw.js` includes `/user/` bypass; verified minified gateway route chunk uses `window.open(..., "_blank", "noopener,noreferrer")`; `./nukelabctl lint all` passed; stack serving updated assets at `http://localhost:8080` |
| PENT-NKL-011 | 2026-06-28 | Security Eng | Pass | Added readiness probe in `backend/app/container/client.py`; spawned `readiness-test`; backend log shows `Container nukelab-server-readinesse2e-readiness-test is ready` before API returns `running`; immediate curl to server URL with access token returns HTTP 200 ttyd HTML; `./nukelabctl lint backend`, `./nukelabctl build backend` pass; container readiness unit tests pass |
| PENT-NKL-006 | 2026-06-29 | Security Eng | Pass | `./scripts/security/check-base-image-pinning.sh --strict` reports 0 unpinned images; `./nukelabctl security --check-base-images` passes; Dockerfiles updated with `@sha256:` digests |
| PENT-NKL-007 | 2026-06-29 | Security Eng | N/A | Process change; created `.github/workflows/security.yml` with signed-commits check in warn-only mode pending team adoption of GPG/SSH signing and branch-protection enforcement |

## Commit Signing Setup Guide

To close PENT-NKL-007, every maintainer must sign commits and the `main` branch must require signed commits.

### Option A — GPG signing

1. Generate a GPG key:

   ```bash
   gpg --full-generate-key
   ```

2. Add the key to your GitHub account (`Settings → SSH and GPG keys → New GPG key`).
3. Configure git locally:

   ```bash
   git config --global user.signingkey <KEY_ID>
   git config --global commit.gpgsign true
   ```

4. Sign commits automatically:

   ```bash
   git commit -S -m "signed commit"
   ```

### Option B — SSH signing

1. Add your SSH key to GitHub (`Settings → SSH and GPG keys → New SSH key`, type **Signing**).
2. Configure git locally:

   ```bash
   git config --global gpg.format ssh
   git config --global user.signingkey "$(cat ~/.ssh/id_ed25519.pub)"
   git config --global commit.gpgsign true
   ```

### Repository enforcement

1. In GitHub, go to `Settings → Branches → main → Edit`.
2. Enable **Require signed commits**.
3. Optional: enable **Require a pull request before merging** and **Require status checks to pass** including `dependency-and-sast-scans`.

### Historical commits

The 339 unsigned commits already on `main` cannot be re-signed without rewriting history. Once enforcement is enabled, only *new* commits pushed to `main` or merged via PR must be signed. The CI job `signed-commits-check` in `.github/workflows/security.yml` is configured with `continue-on-error: true` during the transition; remove that line once enforcement is active.

---

**Pending:** PENT-NKL-007 (commit signing). Enable GPG or SSH signing for all maintainers and turn on branch-protection "Require signed commits" for `main`. PENT-NKL-006 (base image digest pinning) is closed and enforced in `.github/workflows/security.yml`.
