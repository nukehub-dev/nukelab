# Environments

## Purpose

Docker image definitions for user-facing scientific computing environments (base, workspace, default, and development templates).

## Ownership

All files under `environments/`.

## Local Contracts

- Each subdirectory contains a `Dockerfile` defining one environment image.
- `base/` is the shared runtime base layer (nginx + auth-sidecar + non-root user + health endpoint).
- `workspace/` extends `base/` with the IDE foundation (Node.js, Miniforge, nuke-ide).
- `default/` extends `workspace/` with the full nuclear simulation stack.
- `dev/` is a minimal terminal environment extending `base/` with `ttyd` for dev/test.
- Child environments add drop-in nginx configs via `/etc/nginx/conf.d/` and set `NUKELAB_START_COMMAND` to launch their service behind the shared nginx.
- Images are built via `scripts/build-base.sh`, `scripts/build-workspace.sh`, `scripts/build-default.sh`, and `scripts/build-dev.sh` or the CI/CD pipeline.
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
