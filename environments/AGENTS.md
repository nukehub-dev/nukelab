# Environments

## Purpose

Docker image definitions for user-facing scientific computing environments (base, default, and development templates).

## Ownership

All files under `environments/`.

## Local Contracts

- Each subdirectory contains a `Dockerfile` defining one environment image.
- `base/` is the shared base layer; `default/` and `dev/` extend it.
- Images are built via `scripts/build-base.sh` / `scripts/build-dev.sh` or the CI/CD pipeline.

## Work Guidance

- Keep images minimal; pin base images and tool versions where practical.
- Avoid baking secrets into images.
- Update the corresponding environment template records in the backend when image behavior or installed packages change.
- Test image builds locally before committing changes.

## Verification

```bash
./scripts/build-base.sh
./scripts/build-dev.sh
```

## Child NAD Index

- None
