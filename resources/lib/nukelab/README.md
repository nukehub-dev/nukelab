# CPU Count Masking Library

## Problem

Containers with CPU limits (`--cpus`, `--cpuset-cpus`) still expose the **host's** total CPU count via `/sys/devices/system/cpu/online`. This means:

- `python -c "import os; print(os.cpu_count())"` → sees all host cores
- `multiprocessing.cpu_count()` → sees all host cores
- `getconf _NPROCESSORS_ONLN` → sees all host cores
- OpenMP/BLAS/MKL spawn threads for all host cores → CPU thrashing inside limited container

## Solution

`libnukelab_cpu.so` is an **LD_PRELOAD** library that intercepts `sysconf(_SC_NPROCESSORS_ONLN)` and returns the container's **actual** CPU allocation instead of the host's core count.

### Resolution order (first match wins)

1. `NUKELAB_CPU_COUNT` environment variable (user-overridable)
2. `/sys/fs/cgroup/cpu.max` — cgroup v2 CPU quota (e.g. `--cpus=1`)
3. `/sys/fs/cgroup/cpuset.cpus.effective` — cgroup cpuset affinity (e.g. `--cpuset-cpus=0-3`)
4. Real `sysconf()` — host fallback

### Defense layers

| Layer | Mechanism | Survives `su -`? | User can bypass? |
|-------|-----------|------------------|------------------|
| `/etc/ld.so.preload` | System-wide library preload (root-only) | ✅ Yes | ❌ No (needs root) |
| `/etc/profile.d/nukelab-cpu.sh` | Env vars for login shells | ✅ Yes | ⚠️ Only by clearing env |
| Container env vars | `LD_PRELOAD`, `NUKELAB_CPU_COUNT` | ❌ No | ⚠️ Only by clearing env |
| Cgroup fallback | Reads `cpu.max` / `cpuset.cpus.effective` | ✅ Yes | ❌ No (kernel-enforced) |

## Setup

Run `./nukelabctl start` or `./nukelabctl build` — it creates the volume and builds `libnukelab_cpu.so` automatically. No manual steps needed.

## How It Works

1. `./nukelabctl start` creates a named Docker volume `nukelab-cpu-lib` and compiles `libnukelab_cpu.c` into it via a temporary `gcc` container
2. The backend injects two files into every spawned container via `put_archive`:
   - `/etc/ld.so.preload` — system-wide library preload (root-only, survives any env clearing)
   - `/etc/profile.d/nukelab-cpu.sh` — env vars for login shells
3. The volume is mounted read-only into every spawned container at `/usr/local/lib/nukelab/`
4. Container starts with `NUKELAB_CPU_COUNT=N` (matches plan allocation) and `LD_PRELOAD=/usr/local/lib/nukelab/libnukelab_cpu.so`
5. Any program calling `sysconf()` gets the plan's CPU count, not the host's

**Zero configuration required** — no environment variables, no host bind mounts, no hardcoded paths, no host toolchain, no per-container copy overhead.

## Security

- No network access
- No file system access (only reads `/sys/fs/cgroup/*`)
- Only intercepts `sysconf()` for `_SC_NPROCESSORS_ONLN` and `_SC_NPROCESSORS_CONF`
- Falls back to real `sysconf()` when no cgroup limit is present
