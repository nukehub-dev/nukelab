# Production Deployment Guide

**Multi-user resource isolation with cgroup limits, lxcfs, and storage quotas**

This guide covers configuring NukeLab for production environments where users must see and be constrained by their allocated resource plans (CPU, memory, disk).

---

## Table of Contents

1. [Overview](#overview)
2. [Cgroup Controllers](#cgroup-controllers)
3. [lxcfs (Cgroup-Aware /proc)](#lxcfs)
4. [Storage Quotas](#storage-quotas)
5. [Docker vs Podman](#docker-vs-podman)
6. [Verification](#verification)
7. [Troubleshooting](#troubleshooting)

---

## Overview

NukeLab server containers enforce resource limits via Linux cgroups:

| Resource | Enforcement | Visibility (without lxcfs) | Visibility (with lxcfs) |
|----------|-------------|---------------------------|------------------------|
| **CPU** | `NanoCpus` (throttling) + `CpusetCpus` (pinning) | Host CPUs | Allocated CPUs only |
| **Memory** | `Memory` + `MemorySwap` | Host RAM | Allocated RAM only |
| **Disk** | `StorageOpt` (XFS/ZFS/Btrfs) | Host disk | Host disk (use quotas) |

**Key insight:** Cgroups *enforce* limits but `free`/`top`/`nproc` read `/proc` which shows host values by default. **lxcfs** virtualizes `/proc` to show cgroup-aware values.

---

## Cgroup Controllers

### What You Need

For full resource isolation, enable these cgroup v2 controllers:

- `cpu` — CPU throttling (NanoCpus)
- `cpuset` — CPU pinning and visibility (shows only allocated CPUs)
- `memory` — Memory limits
- `io` — I/O throttling (optional)

### Check Current Controllers

```bash
# Available controllers
cat /sys/fs/cgroup/cgroup.controllers

# Enabled for your user session
cat /sys/fs/cgroup/cgroup.subtree_control
```

**Expected output (all enabled):**
```
cpuset cpu io memory hugetlb pids rdma misc dmem
```

### Enable Controllers (systemd Systems)

**For rootful Docker (recommended for production):**

Already available by default. No action needed.

**For rootless Podman (development):**

```bash
sudo mkdir -p /etc/systemd/system/user@.service.d/
sudo tee /etc/systemd/system/user@.service.d/delegate.conf << 'EOF'
[Service]
Delegate=cpu cpuset io memory pids
EOF
sudo systemctl daemon-reload
```

**Log out and log back in** for changes to take effect.

**Verify:**
```bash
cat /sys/fs/cgroup/cgroup.controllers
# Should show: cpuset cpu io memory ...
```

---

## lxcfs

lxcfs is a FUSE filesystem that makes `/proc` files inside containers return cgroup-aware values. Without it, `free -h` shows host RAM; with it, users see their plan limits.

### Installation

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install lxcfs
sudo systemctl enable --now lxcfs
```

**RHEL/CentOS/Fedora:**
```bash
sudo dnf install lxcfs
sudo systemctl enable --now lxcfs
```

**Arch Linux:**
```bash
sudo pacman -S lxcfs
sudo systemctl enable --now lxcfs
```

### Verification

```bash
systemctl is-active lxcfs
# → active

ls /var/lib/lxcfs/proc/
# → cpuinfo  diskstats  loadavg  meminfo  slabinfo  stat  swaps  uptime
```

### Docker Compose Configuration

Mount lxcfs into the **backend** container so it can detect and propagate lxcfs to user containers:

```yaml
# compose.yml (backend service)
services:
  backend:
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./backend:/app:Z
      - /var/lib/lxcfs:/var/lib/lxcfs:ro  # <-- Add this
```

**NukeLab backend automatically detects lxcfs** and mounts these files into each user server container:

- `/var/lib/lxcfs/proc/meminfo` → `/proc/meminfo`
- `/var/lib/lxcfs/proc/cpuinfo` → `/proc/cpuinfo`
- `/var/lib/lxcfs/proc/loadavg` → `/proc/loadavg`
- `/var/lib/lxcfs/proc/stat` → `/proc/stat`
- `/var/lib/lxcfs/proc/swaps` → `/proc/swaps`
- `/var/lib/lxcfs/proc/uptime` → `/proc/uptime`
- `/var/lib/lxcfs/proc/diskstats` → `/proc/diskstats`

### Backend Logs

When lxcfs is active, backend logs show:
```
INFO:lxcfs detected. Cgroup-aware /proc will be mounted into containers.
INFO:Mounted lxcfs /proc files: 7 files
```

---

## Storage Quotas

### Supported Filesystems

| Filesystem | Quota Support | Configuration |
|------------|--------------|---------------|
| **XFS** | ✅ Yes (with `pquota` mount option) | `mount -o prjquota` or fstab |
| **ZFS** | ✅ Yes (refquota) | `zfs set quota=50G pool/dataset` |
| **Btrfs** | ✅ Yes (qgroups) | `btrfs quota enable /path` |
| **overlayfs** (rootless) | ❌ No | Use for dev only |
| **ext4** | ❌ No | Not supported for container quotas |

### XFS with Project Quotas (pquota)

**1. Check current mount:**
```bash
findmnt /var/lib/docker
# or
findmnt /var/lib/containers
```

**2. Remount with pquota (temporary):**
```bash
sudo mount -o remount,prjquota /var/lib/docker
```

**3. Make permanent in `/etc/fstab`:**
```
/dev/mapper/vg-docker /var/lib/docker xfs defaults,prjquota 0 0
```

**4. Enable in Docker daemon** (`/etc/docker/daemon.json`):
```json
{
  "storage-driver": "overlay2",
  "storage-opts": [
    "overlay2.override_kernel_check=true",
    "xfs.pquota=true"
  ]
}
```

**5. Restart Docker:**
```bash
sudo systemctl restart docker
```

### ZFS

**1. Set quota on dataset:**
```bash
sudo zfs create -o mountpoint=/var/lib/docker tank/docker
sudo zfs set quota=500G tank/docker
sudo zfs set refquota=500G tank/docker
```

**2. Configure Docker for ZFS** (`/etc/docker/daemon.json`):
```json
{
  "storage-driver": "zfs"
}
```

**3. Restart Docker:**
```bash
sudo systemctl restart docker
```

### Verify Storage Quotas Work

NukeLab tests storage support by creating a test container. Check backend logs:

```bash
# Successful:
INFO:Storage limits are supported by the current driver.

# Unsupported (rootless/overlayfs):
WARNING:Storage limits not supported: DockerError(...)
Common in rootless dev environments (overlayfs).
Expected in production with XFS(pquota)/ZFS/Btrfs.
```

---

## Docker vs Podman

| Feature | Docker (rootful) | Podman (rootless) |
|---------|------------------|-------------------|
| **CPU/Memory limits** | ✅ Full support | ✅ With cgroup controllers |
| **Cpuset** | ✅ Works out of box | ✅ After enabling delegate |
| **Storage quotas** | ✅ XFS/ZFS/Btrfs | ✅ XFS/ZFS/Btrfs (rootful) |
| **lxcfs** | ✅ Works | ✅ Works |
| **Setup complexity** | Low | Medium |
| **Security** | Root daemon | Rootless (better) |

**Production recommendation:** Use **rootful Docker** or **rootful Podman** for full storage quota support. Rootless Podman works for CPU/memory but storage quotas are limited.

### Docker Socket Path

| Engine | Socket Path | `.env` Setting |
|--------|-------------|----------------|
| Docker | `/var/run/docker.sock` | `DOCKER_SOCKET=/var/run/docker.sock` |
| Podman (rootless) | `$XDG_RUNTIME_DIR/podman/podman.sock` | `DOCKER_SOCKET=/run/user/1000/podman/podman.sock` |
| Podman (rootful) | `/run/podman/podman.sock` | `DOCKER_SOCKET=/run/podman/podman.sock` |

---

## Verification

After setting up everything, verify from inside a user server container:

```bash
# Get a shell inside a running server
podman exec -it nukelab-server-<username>-<servername> bash

# Check memory shows plan limit, not host
free -h
# Expected: Mem: 4.0Gi (for 4GB plan)

# Check CPU count shows allocated, not host
nproc
# Expected: 2 (for 2-core plan)

# Check /proc files
cat /proc/meminfo | grep MemTotal
# Expected: MemTotal: 4194304 kB (4GB)

cat /proc/cpuinfo | grep processor | wc -l
# Expected: 2 (for 2-core plan)
```

**Check container config:**
```bash
podman inspect nukelab-server-<username>-<servername> --format '{{json .HostConfig}}' | \
  python3 -m json.tool | grep -E "(NanoCpus|CpusetCpus|Memory|StorageOpt)"
```

**Expected output:**
```json
"CpusetCpus": "0,1",
"Memory": 4294967296,
"MemorySwap": 4294967296,
"NanoCpus": 2000000000,
```

---

## Troubleshooting

### Issue: `free -h` shows host memory

**Cause:** lxcfs not installed or not mounted into backend.

**Fix:**
```bash
# Install lxcfs
sudo apt install lxcfs && sudo systemctl enable --now lxcfs

# Add to compose.yml backend volumes:
# - /var/lib/lxcfs:/var/lib/lxcfs:ro

# Restart backend
./nukelabctl restart backend
```

### Issue: `nproc` shows all host CPUs

**Cause:** `cpuset` cgroup controller not enabled.

**Fix:**
```bash
# Enable cgroup controllers (see section above)
sudo mkdir -p /etc/systemd/system/user@.service.d/
echo -e "[Service]\nDelegate=cpu cpuset io memory pids" | \
  sudo tee /etc/systemd/system/user@.service.d/delegate.conf
sudo systemctl daemon-reload
# Log out and back in
```

### Issue: Storage limits not applied

**Cause:** Filesystem doesn't support quotas (e.g., overlayfs, ext4).

**Fix:** Use XFS with pquota, ZFS, or Btrfs.

```bash
# Check filesystem
findmnt /var/lib/docker

# For XFS - check pquota
xfs_quota -x -c 'report -p' /var/lib/docker
```

### Issue: `DockerError(500, 'crun: controller cpuset is not available')`

**Cause:** Podman rootless without cgroup delegation.

**Fix:** Enable cgroup controllers (see section above).

### Issue: Backend can't detect lxcfs

**Cause:** `/var/lib/lxcfs` not mounted into backend container.

**Fix:** Add volume mount to `compose.yml`:
```yaml
backend:
  volumes:
    - /var/lib/lxcfs:/var/lib/lxcfs:ro
```

---

## Traefik Security Hardening

NukeLab uses a **two-layer rate limiting architecture** designed for platforms serving 100M+ users across institutions, labs, and companies:

### Why Two Layers?

**The NAT problem:** Universities and companies put thousands of users behind a single public IP. IP-based rate limiting would block entire institutions.

| Layer | Technology | Scope | Purpose |
|-------|-----------|-------|---------|
| **Layer 1** | Traefik | Per-IP | DDoS / bot protection only (very high thresholds) |
| **Layer 2** | FastAPI + Redis | Per-user (JWT identity) | Fair throttling, role-based tiers |

### Layer 1: Traefik DDoS Protection

Traefik middlewares in `infrastructure/traefik/dynamic/middlewares.yml`:

| Middleware | Rate | Burst | Purpose |
|-----------|------|-------|---------|
| `ddos-protect` | 10,000/min | 5,000 | Catch bot floods, DDoS attacks |
| `ddos-protect-ws` | 5,000/min | 2,000 | WebSocket connection floods |

These thresholds are intentionally **extremely high** — a single university with 10,000 active users will never hit them. They only catch malicious traffic.

### Layer 2: FastAPI Per-User Rate Limiting

The `RateLimitMiddleware` (`backend/app/middleware/rate_limit.py`) enforces limits by **JWT user identity**, not IP. It uses Redis fixed-window counters keyed by `username` (from JWT `sub` claim) + role.

**Role-based tiers (requests per minute):**

| Role | General API | Strict* | WebSocket |
|------|------------|---------|-----------|
| `guest` | 30 | 15 | 30 |
| `user` | 120 | 60 | 30 |
| `support` | 300 | 150 | 30 |
| `moderator` | 300 | 150 | 30 |
| `admin` | 600 | 300 | 30 |
| `super_admin` | Unlimited | Unlimited | Unlimited |

\* Strict = admin mutations, bulk actions, password reset endpoints (0.5× multiplier)

**Algorithm:** Redis `INCR` with TTL on a fixed-window bucket (`rate_limit:{user}:{bucket}:{suffix}`). Redis failures **fail open** — legitimate traffic is never blocked by infrastructure issues.

**Exempt paths:** Health checks, auth endpoints (handled by slowapi IP limits), docs, system config.

### Security Headers

NukeLab sets security headers at **two layers** for defense in depth:

**Layer 1 — Traefik (all traffic):**

The `security-headers@file` middleware adds:

- `Strict-Transport-Security` (HSTS, 1 year, includeSubDomains, preload)
- `X-Frame-Options: SAMEORIGIN`
- `X-Content-Type-Options: nosniff`
- `X-XSS-Protection: 1; mode=block`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy` (disables unused browser features)
- `Server: NukeLab` (replaces fingerprinting header)

The `csp-header@file` middleware adds a Content Security Policy baseline:

```
default-src 'self';
script-src 'self' 'unsafe-inline' 'unsafe-eval';
style-src 'self' 'unsafe-inline';
img-src 'self' data: blob:;
font-src 'self';
connect-src 'self' ws: wss:;
frame-ancestors 'self';
base-uri 'self';
form-action 'self';
```

These middlewares are applied via chains:

| Router | Chain | Middlewares |
|--------|-------|-------------|
| `/api/*` | `api-chain@file` | ddos-protect + security-headers + csp-header |
| `/api/auth/*` | `auth-chain@file` | ddos-protect + security-headers + csp-header |
| `/ws` | `ws-chain@file` | ddos-protect-ws + security-headers + csp-header |
| `/` (frontend) | `frontend-chain@file` | security-headers + csp-header + permissions-policy |
| `/user/{username}` | `frontend-chain@file` | security-headers + csp-header + permissions-policy |

**Layer 2 — FastAPI (defense in depth):**

`SecurityHeadersMiddleware` (`backend/app/core/security_headers_asgi.py`) is a **pure ASGI middleware** that injects headers at the `http.response.start` message level. This guarantees headers are present even on 500 Internal Server Error responses generated by Starlette's exception handler — something `BaseHTTPMiddleware` cannot do.

Additional protections added by the FastAPI layer:

- `Cross-Origin-Resource-Policy: same-origin` — prevents cross-origin inclusion of API responses in `<img>` / `<script>` tags (Spectre mitigation)
- `Cache-Control: no-store` — automatically applied to `/api/auth/*` and `/api/admin/*` endpoints to prevent browsers from caching tokens or personal data
- `Clear-Site-Data` — logout endpoint instructs the browser to wipe cache, cookies, and storage

The middleware is skipped when `security_headers_enabled=false`.

#### Customizing CSP

If you add external integrations (e.g., Sentry, Google Analytics, Stripe), update the CSP in `infrastructure/traefik/dynamic/middlewares.yml`:

```yaml
csp-header:
  headers:
    contentSecurityPolicy: "default-src 'self'; script-src 'self' 'unsafe-inline' https://js.sentry-cdn.com; connect-src 'self' ws: wss: https://*.sentry.io;"
```

Traefik auto-reloads dynamic config within ~2 seconds.

#### Strict CSP for Production

For production builds that do not require `eval()` (e.g., React production builds without dynamic code execution), switch to the stricter CSP:

```yaml
# In compose.yml — change chain references
- "traefik.http.routers.frontend.middlewares=security-headers@file,csp-header-strict@file,permissions-policy@file"
```

The `csp-header-strict@file` middleware removes `'unsafe-eval'` from `script-src`. If your build is clean of inline scripts, you can also remove `'unsafe-inline'` and use nonce-based CSP (requires build-pipeline integration).

#### Disabling HSTS During Initial HTTPS Setup

To avoid HSTS lock-in while testing HTTPS:

1. Set `forceSTSHeader: false` in `infrastructure/traefik/dynamic/middlewares.yml`
2. Restart Traefik: `./nukelabctl restart traefik`

Once your TLS certificate is working, re-enable it.

#### Traefik Dashboard in Production

The Traefik dashboard (`api.insecure: true`) is enabled for development. **In production**, either:

- Disable it entirely in `infrastructure/traefik/traefik.yml`
- Or protect it behind an IP allowlist + basic-auth middleware

### Admin Panel IP Allowlist

The `admin-allowlist@file` middleware restricts access to `/admin` and `/api/admin/*` to private network ranges by default. **Override this in production** by editing `infrastructure/traefik/dynamic/middlewares.yml`:

```yaml
admin-allowlist:
  ipAllowList:
    sourceRange:
      - "203.0.113.0/24"   # Your office IP
      - "198.51.100.0/24"  # Your VPN range
```

To apply the allowlist, add the middleware label to the backend service in `compose.yml`:

```yaml
labels:
  - "traefik.http.routers.backend-admin.rule=PathPrefix(`/api/admin`)"
  - "traefik.http.routers.backend-admin.priority=90"
  - "traefik.http.routers.backend-admin.middlewares=admin-allowlist@file,api-chain@file"
  - "traefik.http.routers.backend-admin.service=backend"
```

### Customizing Rate Limits

**Traefik (DDoS thresholds):**

Edit `infrastructure/traefik/dynamic/middlewares.yml` — Traefik auto-reloads within ~2 seconds (no restart needed).

**FastAPI (User tiers):**

Set environment variables in `.env`:

```env
RATE_LIMIT_GUEST_RPM=30
RATE_LIMIT_USER_RPM=120
RATE_LIMIT_ADMIN_RPM=600
RATE_LIMIT_SUPER_ADMIN_RPM=3000
```

Restart the backend:

```bash
./nukelabctl restart backend
```

### Verify Rate Limiting

**Test DDoS layer (Traefik):**

```bash
# Should succeed
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/api/health

# Flood from one IP — should trigger Traefik 429 only at 10K+/min
ab -n 20000 -c 100 http://localhost:8080/api/health
```

**Test user layer (FastAPI):**

```bash
# Authenticated request — should succeed
curl -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/servers

# Flood as authenticated user — should trigger FastAPI 429 at tier limit
for i in {1..150}; do
  curl -s -o /dev/null -w "%{http_code}\n" \
    -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/servers
done
# Expected: mostly 200, then 429 with Retry-After header
```

## Quick Production Checklist

- [ ] Cgroup controllers enabled (`cpuset cpu memory`)
- [ ] lxcfs installed and running
- [ ] lxcfs mounted into backend container
- [ ] Storage filesystem supports quotas (XFS/ZFS/Btrfs)
- [ ] Docker socket path correct in `.env`
- [ ] Backend logs show `Applied CPU limit`, `Applied memory limit`
- [ ] User containers show correct CPU count (`nproc`)
- [ ] User containers show correct memory (`free -h`)
- [ ] Storage quotas enforced (check with `podman inspect`)
- [ ] Traefik DDoS protection active (very high thresholds — test with `ab -n 20000`)
- [ ] FastAPI per-user rate limiting active (test authenticated user at tier limit)
- [ ] Admin IP allowlist restricted to office/VPN ranges
- [ ] HSTS headers present (`curl -I https://your-domain`)

---

## References

- [Linux cgroup v2 documentation](https://docs.kernel.org/admin-guide/cgroup-v2.html)
- [lxcfs GitHub](https://github.com/lxc/lxcfs)
- [Docker storage drivers](https://docs.docker.com/storage/storagedriver/)
- [Podman rootless containers](https://github.com/containers/podman/blob/main/docs/tutorials/rootless_tutorial.md)
