# CPU Masking Library

## Problem

Containers with CPU limits (`--cpus`, `--cpuset-cpus`) still expose the **host's** view:

- `python -c "import os; print(os.cpu_count())"` → sees all host cores
- `multiprocessing.cpu_count()` → sees all host cores
- `getconf _NPROCESSORS_ONLN` → sees all host cores
- OpenMP/BLAS/MKL spawn threads for all host cores → CPU thrashing inside limited container
- `top` / `htop` / `psutil` read `/proc/stat`, which is **host-wide** — an idle container sees 100% CPU when a neighbor is busy

## Solution

`libnukelab_cpu.so` is an **LD_PRELOAD** library that gives processes a container-scoped CPU view:

1. **CPU count** — intercepts `sysconf(_SC_NPROCESSORS_ONLN/_CONF)` and returns the container's actual allocation instead of the host's core count.
2. **CPU usage** — intercepts read-only `open()`/`fopen()` of `/proc/stat` and serves a synthesized stat file derived from the cgroup CPU counters (`cpu.stat` / `cpuacct`), so monitoring tools report this container's usage. The synthesized file carries one aggregate `cpu` line plus one `cpuN` line per allocated CPU (per-cpu totals are split evenly; aggregate sums stay exact). Idle time is derived from wall-clock capacity since boot, which is what delta-based readers expect.

Synthesis only activates when a CPU restriction is visible; otherwise the real `/proc/stat` is served, which is correct on bare metal. Any synthesis failure falls through to the real file — the interception can never break readers.

### Resolution order (first match wins)

1. `NUKELAB_CPU_COUNT` environment variable (user-overridable)
2. `/sys/fs/cgroup/cpu.max` — cgroup v2 CPU quota (e.g. `--cpus=1`)
3. `/sys/fs/cgroup/cpu/cpu.cfs_quota_us` — cgroup v1 CPU quota
4. `/sys/fs/cgroup/cpuset.cpus.effective` — cgroup cpuset affinity, when narrower than the host (e.g. `--cpuset-cpus=0-3`)
5. Real `sysconf()` / real `/proc/stat` — host fallback

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
5. Any program calling `sysconf()` gets the plan's CPU count, and any program reading `/proc/stat` gets the container's CPU usage, not the host's

**Zero configuration required** — no environment variables, no host bind mounts, no hardcoded paths, no host toolchain, no per-container copy overhead.

## Limitations

- Only affects dynamically-linked processes that load the preload (static binaries, e.g. Go tools, bypass `LD_PRELOAD`).
- `/proc/stat` synthesis fabricates per-cpu lines (cgroup exposes only aggregate counters) and reports `iowait`/`irq`/`steal` as 0.
- `stat()` on `/proc/stat` is not intercepted; size/metadata still come from procfs.

## Security

- No network access
- File reads limited to `/sys/fs/cgroup/*`; synthesized content is served from an anonymous memfd
- Intercepts `sysconf()` CPU-count queries and read-only opens of `/proc/stat` only
- Falls back to the real `sysconf()`/`open()` when no cgroup limit is present or synthesis fails
