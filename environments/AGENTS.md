# Environments

## Purpose

Docker image definitions for user-facing scientific computing environments (base, workspace, radiation-transport, and development templates).

## Ownership

All files under `environments/`.

## Local Contracts

- Each subdirectory contains a `Dockerfile` defining one environment image.
- `base/` is the shared runtime base layer (nginx + auth-sidecar + non-root user + health endpoint).
- `workspace/` extends `base/` with the IDE foundation (Node.js, Miniforge, nuke-ide).
- `radiation-transport/` extends `workspace/` with the full nuclear simulation stack (MOAB, OpenMC, DAGMC, Geant4, PyNE, etc.).
- In `radiation-transport/Dockerfile`, `paraview`/`vtk` (conda) and `cadquery`/`cadquery-ocp`/`cadquery_vtk` (pip, via paramak) must stay pinned to the verified combo, and the final `conda install --force-reinstall` of the VTK family must run after all pip installs — pip's `cadquery_vtk` shares the `vtkmodules` namespace with conda's `vtk` and clobbers files, which breaks `dagmc.visualize`/ParaView with "not compatible with vtkmodules.*" errors.
- `dev/` is a minimal terminal environment extending `base/` with `ttyd` for dev/test.
- Child environments add drop-in nginx configs via `/etc/nginx/conf.d/` and set `NUKELAB_START_COMMAND` to launch their service behind the shared nginx.
- Images are built via `scripts/environments/build-base.sh`, `scripts/environments/build-workspace.sh`, `scripts/environments/build-radiation-transport.sh`, and `scripts/environments/build-dev.sh` or the CI/CD pipeline.
- `./nukelabctl build` only builds backend/frontend compose images. To build an environment image, use `./nukelabctl build env <name>` (e.g. `./nukelabctl build env radiation-transport`).
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
