# GPU Setup (NVIDIA)

NukeLab can attach NVIDIA GPUs to user server containers. When enabled, a plan
with `gpu_limit > 0` spawns its containers with GPU access, quota accounting
tracks GPU usage, and per-server metrics include GPU utilization.

## Host prerequisites

1. **NVIDIA driver** installed on the host (`nvidia-smi` works).
2. **NVIDIA Container Toolkit** (`nvidia-container-toolkit`) installed.
3. **Podman (rootless or rootful)** — generate a CDI spec so Podman can
   resolve GPU devices:

   ```bash
   sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
   ```

   Verify with:

   ```bash
   podman run --rm --device nvidia.com/gpu=all <any-image> nvidia-smi -L
   ```

   The toolkit injects the host driver libraries into the container, so
   `nvidia-smi` and dynamically linked CUDA applications work even in images
   without CUDA installed.
4. **Docker** — the toolkit registers the `nvidia` runtime instead; no CDI
   spec is required. The backend emits the classic `DeviceRequests`
   (`Driver: nvidia`) payload automatically when it detects a Docker engine.

## Enabling

Set in `.env.production` / `.env.development`:

```bash
GPU_ENABLED=true
# Optional, Podman only — override the CDI device spec:
# GPU_CDI_DEVICE=nvidia.com/gpu=all
# Optional — exclusive device pool (see "Exclusive allocation" below):
# GPU_DEVICES=nvidia.com/gpu=0,nvidia.com/gpu=1
```

These variables are passed to the `backend` and `celery-worker` services in
`compose.yml` (scheduled/auto spawns and GPU metrics collection run in the
worker). Restart the stack after changing them.

With `GPU_ENABLED=false` (default), selecting a GPU plan fails the spawn with a
clear error instead of silently starting without a GPU.

## Exclusive allocation

By default (`GPU_DEVICES` empty) every GPU server receives the whole
`GPU_CDI_DEVICE` spec — all GPUs, shared, time-sliced by the NVIDIA driver.
The per-user `max_gpu_total` quota then acts as a concurrency limit on GPU
servers, not as physical ownership.

Set `GPU_DEVICES` to a comma-separated pool of CDI device names to switch to
**exclusive whole-GPU assignment**:

```bash
GPU_DEVICES=nvidia.com/gpu=0,nvidia.com/gpu=1,nvidia.com/gpu=2
```

Each unit of a plan's `gpu_limit` then reserves one physical device for that
server's lifetime (recorded in the `gpu_allocations` table, released on
stop/delete, reconciled automatically if state drifts). When the pool is
exhausted, spawns fail with HTTP 429 "No GPUs available on the host". On a
single-GPU host use `GPU_DEVICES=nvidia.com/gpu=0` to enforce one GPU server
at a time platform-wide.

GPU compute cannot be subdivided like CPU/RAM on consumer cards (no MIG on
GeForce); exclusive whole-GPU assignment is the strongest isolation available.
VRAM is the practical ceiling in shared mode — concurrent containers share the
GPU's memory pool and can OOM each other.

## Using GPUs

1. Build the CUDA environment image (extends `workspace` with the CUDA
   toolkit):

   ```bash
   ./nukelabctl build env gpu
   ```

2. In the admin UI, create an **Environment** record pointing at the built
   image (`nukelab-gpu:latest`).
3. Create or edit a **Plan** with **GPU** (`gpu_limit`) greater than 0. With
   exclusive allocation enabled, `gpu_limit` counts whole physical GPUs per
   server; keep the sum of concurrent GPU usage within the `GPU_DEVICES` pool.
4. Users pick the GPU plan at spawn. Their profile quota tile shows GPU
   `used / limit` once their quota's `max_gpu_total` allows it (adjust under
   admin quotas or the system default limits).

Verify inside the server terminal:

```bash
nvidia-smi
```

## Metrics

While a GPU server is running, the metrics collector executes
`nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu`
inside its container and stores `gpu_percent`, `gpu_memory_used`,
`gpu_memory_total`, and `gpu_temperature` alongside the regular CPU/memory
metrics (visible on the usage pages as "Peak GPU" and friends).

Limitation: the readings are **whole-GPU**, not per-container. On a shared
multi-tenant GPU the numbers reflect all users of that GPU.

## Notes

- GPU attachment composes with container hardening (non-root user, dropped
  capabilities, read-only rootfs) — the CDI spec grants device-node access
  without extra privileges.
- Docker engine support is implemented (`Driver: nvidia` + `Count`) but only
  the rootless Podman + CDI path is covered by the automated tests and has
  been verified on a live host.
