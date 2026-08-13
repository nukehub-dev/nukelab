# Environments

## Purpose

Docker image definitions for user-facing scientific computing environments (base, workspace, radiation-transport, gpu, and development templates).

## Ownership

All files under `environments/`.

## Local Contracts

- Each subdirectory contains a `Dockerfile` defining one environment image.
- `base/` is the shared runtime base layer (nginx + auth-sidecar + non-root user + health endpoint).
- Container health is defined at the runtime layer, not in images: OCI image format drops Dockerfile `HEALTHCHECK` and Kubernetes ignores it, so `docker_driver.py` injects a uniform healthcheck (`/usr/local/bin/nukelab-healthcheck.sh`, 30s interval / 90s start-period / 3 retries) into every spawned container's create config — the same definition a future k8s driver translates into pod probes. `base/healthcheck.sh` probes nginx `/health` and, when `NUKELAB_AUTH_ENABLED=true`, the sidecar directly on `:8081` (not via `/auth/health` — nginx rewrites sidecar outages to a 200 starting.html, which would mask the failure). Child images declare app probes via `ENV NUKELAB_HEALTH_PROBE_URLS` (`dev/` → ttyd :7681, `workspace/` → IDE :3000, inherited by `gpu/` and `radiation-transport/`). Process-level kills (sidecar/app dead, nginx alive) flip `State.Health.Status` to unhealthy, which the backend `HealthCheckService` uses for auto-restart after 3 consecutive failures.
- `workspace/` extends `base/` with the IDE foundation (Node.js, Miniforge, nuke-ide). The nuke-ide build passes `NUKE_EXTENSIONS=all` so the NukeLab-only `nukelab-integration` extension (excluded from nuke-ide builds by default) is bundled.
- `radiation-transport/` extends `workspace/` with the full nuclear simulation stack (MOAB, OpenMC, DAGMC, Geant4, PyNE, etc.).
- `radiation-transport/` registers its `/opt/nuke` prefix env system-wide via `conda config --system --append envs_dirs /opt`: the image builds as root, so without this `conda env list` (used by nuke-core for environment discovery) would not report the env for the runtime account (uid 65532).
- `workspace/` runs Xvfb for headless rendering: conda-forge ParaView/VTK are X11/GLX-only builds and abort with "bad X server connection" when creating a render window without an X connection, even offscreen. The image installs `xvfb`, sets `DISPLAY=:99`, and points `NUKELAB_START_COMMAND` at `start-ide.sh`, which launches Xvfb before the IDE. The nuke-ide visualizer's `serve.py` must keep `os.environ.setdefault("DISPLAY", "")` (not force `DISPLAY = ""`) so the Xvfb display reaches the visualizer server process. Rendering under Xvfb is software (llvmpipe); the `gpu/` env must use EGL instead if it ever needs GPU-accelerated GL.
- `gpu/` extends `workspace/` with the CUDA toolkit for GPU plans.
- `dev/` is a minimal terminal environment extending `base/` with `ttyd` for dev/test.
- Child environments add drop-in nginx configs via `/etc/nginx/conf.d/` and set `NUKELAB_START_COMMAND` to launch their service behind the shared nginx.
- `base/starting.html` is served by nginx (200) instead of a raw 5xx while the environment app is still booting (`error_page 500 502 503 504` in `base/nginx.conf`); it auto-reloads until the app is up, so front proxies (e.g. Cloudflare) never surface a 502 page. Changes to it only require rebuilding `base` and child images.
- Images are built via `scripts/environments/build-base.sh`, `scripts/environments/build-workspace.sh`, `scripts/environments/build-radiation-transport.sh`, `scripts/environments/build-gpu.sh`, and `scripts/environments/build-dev.sh` or the CI/CD pipeline.
- `./nukelabctl build` only builds backend/frontend compose images. To build an environment image, use `./nukelabctl build env <name>` (e.g. `./nukelabctl build env radiation-transport`). Building `base` (directly or via `env all`) first builds the `nukelab-auth-sidecar` image, because `base/Dockerfile` embeds the sidecar binary via `COPY --from=nukelab-auth-sidecar:latest`.
- Add `--no-cache` to build an environment image without reusing the layer cache, e.g. `./nukelabctl build env workspace --no-cache` (also forwarded to the sidecar build).
- `scripts/build-all.sh` builds the whole set (sidecar first, then base, then the derived images).

## Work Guidance

- Keep images minimal; pin base images and tool versions where practical.
- Avoid baking secrets into images.
- Update the corresponding environment template records in the backend when image behavior or installed packages change.
- Test image builds locally before committing changes.

## Verification

```bash
./scripts/build-all.sh
```

## Child NAD Index

- None
