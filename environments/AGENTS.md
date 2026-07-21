# Environments

## Purpose

Docker image definitions for user-facing scientific computing environments (base, workspace, radiation-transport, gpu, and development templates).

## Ownership

All files under `environments/`.

## Local Contracts

- Each subdirectory contains a `Dockerfile` defining one environment image.
- `base/` is the shared runtime base layer (nginx + auth-sidecar + non-root user + health endpoint).
- `workspace/` extends `base/` with the IDE foundation (Node.js, Miniforge, nuke-ide).
- `radiation-transport/` extends `workspace/` with the full nuclear simulation stack (MOAB, OpenMC, DAGMC, Geant4, PyNE, etc.).
- In `radiation-transport/Dockerfile`, `trame` must stay pinned to `<3` (the nuke-ide visualizer imports `trame.ui.vuetify2`/`trame.widgets.vuetify2`, removed in trame 3.x) and `setuptools` to `<81` (trame 2.x's `trame/ui/__init__.py` calls `pkg_resources.declare_namespace`, removed in setuptools 81).
- `radiation-transport` runs Xvfb for headless ParaView rendering: conda-forge ParaView/VTK are X11/GLX-only builds and abort with "bad X server connection" when creating a render window without an X connection, even offscreen. The image installs `xvfb`, sets `DISPLAY=:99`, and overrides `NUKELAB_START_COMMAND` with `start-ide.sh`, which launches Xvfb before the IDE. The nuke-ide visualizer's `serve.py` must keep `os.environ.setdefault("DISPLAY", "")` (not force `DISPLAY = ""`) so the Xvfb display reaches the visualizer server process.
- `gpu/` extends `workspace/` with the CUDA toolkit for GPU plans.
- `dev/` is a minimal terminal environment extending `base/` with `ttyd` for dev/test.
- Child environments add drop-in nginx configs via `/etc/nginx/conf.d/` and set `NUKELAB_START_COMMAND` to launch their service behind the shared nginx.
- `base/starting.html` is served by nginx (200) instead of a raw 5xx while the environment app is still booting (`error_page 500 502 503 504` in `base/nginx.conf`); it auto-reloads until the app is up, so front proxies (e.g. Cloudflare) never surface a 502 page. Changes to it only require rebuilding `base` and child images.
- Images are built via `scripts/environments/build-base.sh`, `scripts/environments/build-workspace.sh`, `scripts/environments/build-radiation-transport.sh`, `scripts/environments/build-gpu.sh`, and `scripts/environments/build-dev.sh` or the CI/CD pipeline.
- `./nukelabctl build` only builds backend/frontend compose images. To build an environment image, use `./nukelabctl build env <name>` (e.g. `./nukelabctl build env radiation-transport`).
- Add `--no-cache` to build an environment image without reusing the layer cache, e.g. `./nukelabctl build env workspace --no-cache`.
- `scripts/build-all.sh` builds the whole set.

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
