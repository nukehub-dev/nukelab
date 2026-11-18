# CI Scripts

## Purpose

Reproducible helpers used by the GitHub Actions workflows. `e2e-stack.sh`
builds, starts, waits on, and stops the disposable production stack that runs
the browser suite; the same commands work on a local checkout.

## Ownership

All files under `scripts/ci/`. Workflow definitions and the tests they invoke
remain owned by `.github/workflows/` and their respective domains.

## Local Contracts

- `e2e-stack.sh` takes exactly one subcommand: `build [--workspace]`, `start`,
  `wait`, `stop`, or `fixtures`. Unknown subcommands and flags exit non-zero.
- `build` builds the backend/frontend compose images, the volume helper, the
  base environment, and fixture A/B; `--workspace` builds `base`, `conda-base`
  and `workspace` instead, without the helper/fixtures the IDE suite does not
  use. `fixtures` builds only the A/B runtime images.
- `start` runs `./nukelabctl start all --no-build`; `wait` polls the backend
  health endpoint, the frontend origin, and admin login with a bounded
  deadline; `stop` uses `./nukelabctl stop all --include-servers` and then
  stops any remaining `nukelab.managed=true` containers.
- Fixtures build from `frontend/e2e/fixtures/runtime.Dockerfile`, passing
  `BASE_IMAGE` and `VARIANT` (`A` or `B`) and tagging
  `nukelab-e2e-runtime:a` / `nukelab-e2e-runtime:b` by default. Because the
  Dockerfile uses repo-root-relative `COPY` paths, the script stages the
  fixture tree in a temporary repo-shaped build context instead of sending the
  repository-root context through the root `.dockerignore`.
- The helper image builds from the repository root with
  `services/volume-helper/Dockerfile`; the per-Dockerfile ignore file limits
  the context to the reviewed backend archive module and helper sources.
- `CONTAINER_ENGINE` is honored when set (`docker` or `podman`), otherwise it
  is auto-detected. Process environment values take precedence over `.env`
  values, matching `nukelabctl`; do not append duplicate keys to `.env` to
  override a value.
- Readiness and cleanup use bounded polls and idempotent stops. Only
  platform-managed containers and the disposable compose project are touched;
  never prune unrelated host resources.

## Work Guidance

- Keep the script a thin orchestrator over `nukelabctl` and the container
  engine. Add shared shell helpers to `scripts/lib.sh`, not here.
- Do not print tokens, env files, or full compose configuration. CI uploads
  Playwright reports, traces, and targeted container logs on failure only.
- CI browser jobs must keep `E2E_EXTERNAL_SERVER=1` and a fully started stack
  behind `BASE_URL`; combined tests are enabled with `E2E_COMBINED=1`.
- The workspace browser job builds `conda-base` and `workspace` and runs the
  `@workspace` tag before image publication.

## Verification

```bash
bash -n scripts/ci/e2e-stack.sh
shellcheck -x scripts/ci/e2e-stack.sh
shfmt -d scripts/ci/e2e-stack.sh
```

## Child NAD Index

- None
