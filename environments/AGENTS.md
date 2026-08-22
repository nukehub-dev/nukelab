# Environments

## Purpose

Docker image definitions for the NukeLab platform runtime images (`base`,
`conda-base`, `workspace`, and `dev`). Domain-specific scientific computing
stacks (`radiation-transport`, `gpu-toolkit`, `moose`, `cardinal`, `openfoam`)
live as toolchain images in the separate `nukelab-environments` repository and
are mounted into `nukelab-environment-workspace` at container start time.

## Ownership

All files under `environments/`.

## Local Contracts

- Each subdirectory contains a `Dockerfile` defining one environment image.
- `base/` is the shared runtime base layer (nginx + auth-sidecar + non-root user + health endpoint).
- `conda-base/` is the shared conda/Python/build foundation used by `workspace/` and by scientific toolchain images in `nukelab-environments`. Keeping it separate from `workspace/` means IDE updates do not force rebuilds of heavy C++/Fortran scientific stacks. It also installs `/usr/local/bin/nukelab-generate-toolchain-manifest` (`generate-toolchain-manifest.py`), the canonical generator every toolchain image runs during its build to produce `/opt/nuke/nukelab-toolchain.json` — so changing manifest semantics requires a conda-base rebuild/publish before toolchain images pick it up.
- Container health is defined at the runtime layer, not in images: OCI image format drops Dockerfile `HEALTHCHECK` and Kubernetes ignores it, so `docker_driver.py` injects a uniform healthcheck (`/usr/local/bin/nukelab-healthcheck.sh`, 30s interval / 90s start-period / 3 retries) into every spawned container's create config — the same definition a future k8s driver translates into pod probes. `base/healthcheck.sh` probes nginx `/health` and, when `NUKELAB_AUTH_ENABLED=true`, the sidecar directly on `:8081` (not via `/auth/health` — nginx rewrites sidecar outages to a 200 starting.html, which would mask the failure). Child images declare app probes via `ENV NUKELAB_HEALTH_PROBE_URLS` (`dev/` → ttyd :7681, `workspace/` → IDE :3000). Process-level kills (sidecar/app dead, nginx alive) flip `State.Health.Status` to unhealthy, which the backend `HealthCheckService` uses for auto-restart after 3 consecutive failures.
- `workspace/` extends `conda-base/` with the IDE foundation (Node.js, Miniforge, nuke-ide). The nuke-ide build passes `NUKE_EXTENSIONS=all` so the NukeLab-only `nukelab-integration` extension (excluded from nuke-ide builds by default) is bundled.
- `workspace/` runs Xvfb for headless rendering: conda-forge ParaView/VTK are X11/GLX-only builds and abort with "bad X server connection" when creating a render window without an X connection, even offscreen. The image installs `xvfb`, sets `DISPLAY=:99`, and points `NUKELAB_START_COMMAND` at `start-ide.sh`, which launches Xvfb before the IDE. The nuke-ide visualizer's `serve.py` must keep `os.environ.setdefault("DISPLAY", "")` (not force `DISPLAY = ""`) so the Xvfb display reaches the visualizer server process. Rendering under Xvfb is software (llvmpipe).
- `dev/` is a minimal terminal environment extending `base/` with `ttyd` for dev/test.
- Child environments add drop-in nginx configs via `/etc/nginx/conf.d/` and set `NUKELAB_START_COMMAND` to launch their service behind the shared nginx.
- `base/starting.html` is served by nginx (200) instead of a raw 5xx while the environment app is still booting (`error_page 500 502 503 504` in `base/nginx.conf`); it auto-reloads until the app is up, so front proxies (e.g. Cloudflare) never surface a 502 page. Changes to it only require rebuilding `base` and child images.
- Images are built via `scripts/environments/build-base.sh`, `scripts/environments/build-conda-base.sh`, `scripts/environments/build-workspace.sh`, and `scripts/environments/build-dev.sh` or the CI/CD pipeline.
- `./nukelabctl build` only builds backend/frontend compose images. To build a platform environment image, use `./nukelabctl build env <name>` (e.g. `./nukelabctl build env workspace`). Building `base` (directly or via `env all`) first builds the `nukelab-auth-sidecar` image, because `base/Dockerfile` embeds the sidecar binary via `COPY --from=nukelab-auth-sidecar:latest`.
- Add `--no-cache` to build an environment image without reusing the layer cache, e.g. `./nukelabctl build env workspace --no-cache` (also forwarded to the sidecar build).
- `scripts/build-all.sh` builds the platform runtime images (sidecar first, then base, conda-base, workspace, and dev). Scientific toolchain images are built from `nukelab-environments`.

## Runtime composition

The platform uses **runtime composition** to combine the workspace runtime with
scientific toolchains:

1. The backend spawns a container from `nukelab-environment-workspace`.
2. If the selected `EnvironmentTemplate` has a `tool_image`, the backend mounts
   a shared named volume (copied once per node from that toolchain image,
   typically at `/opt/nuke`) read-only into the workspace container. The
   volume is invalidated and re-populated automatically when the local image
   changes; `./nukelabctl cache-toolchain <image> [--force]` pre-populates or
   refreshes it.
3. Environment variables declared in the toolchain manifest are injected into
   the container: `env_prepend` entries (e.g. `PATH`, `LD_LIBRARY_PATH`) are
   prepended to the runtime container's existing values, and `env` scalars
   (e.g. code-specific data paths) are applied only when not already set
   explicitly.

This design is compatible with Kubernetes: a future k3s driver implements the
same flow using an init container to populate an `emptyDir` volume and the same
manifest-based env injection.

## Related repositories

- `nukelab-environments` — domain-specific scientific computing toolchain
  images (`radiation-transport`, `gpu-toolkit`, `moose`, `cardinal`, `openfoam`)
  that extend the published `nukelab-environment-conda-base` image.

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
