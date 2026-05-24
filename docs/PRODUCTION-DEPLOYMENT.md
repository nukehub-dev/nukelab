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
./manage.sh restart backend
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

---

## References

- [Linux cgroup v2 documentation](https://docs.kernel.org/admin-guide/cgroup-v2.html)
- [lxcfs GitHub](https://github.com/lxc/lxcfs)
- [Docker storage drivers](https://docs.docker.com/storage/storagedriver/)
- [Podman rootless containers](https://github.com/containers/podman/blob/main/docs/tutorials/rootless_tutorial.md)
