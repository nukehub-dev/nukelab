# CI Scripts

## Purpose

Reproducible helpers used by the GitHub Actions workflows. `e2e-stack.sh`
builds, starts, waits on, and stops the disposable production stack that runs
the browser suite; the same commands work on a local checkout.
`seed-jobs-fixture.py` seeds the zero-cost batch-job plans and approved
local-identity revision used by the job browser lane, and `jobs-drill.sh` runs
the opt-in worker/broker interruption drill. The same commands work locally.

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
- `seed-jobs-fixture.py` runs inside the backend container, requires
  `NUKELAB_JOBS_SEED_ALLOW=1`, an enabled submission gate, and the local
  `nukelab-e2e-runtime:a` image. It idempotently creates/reuses the
  `jobs-e2e-cpu` and `jobs-e2e-filler` plans plus the `jobs-e2e-runtime`
  template and an approved local-identity revision. It prints one JSON object
  with fixture ids and never prints secrets or environment values.
- `jobs-drill.sh` assumes a dedicated running stack unless `--start` or
  `--build` is passed. It submits one real zero-cost job, interrupts
  `celery-worker` (default) or `redis`, restarts it, and asserts one job row,
  one create/start event, one terminal result, one completed volume guard and
  no negative credit transactions from the database, API and Docker events.
  `--dry-run` performs read-only preflight, `--stop` stops the stack, and the
  default run leaves an already-running stack alone except for its own volume
  and containers.
- The batch-job browser lane runs with `E2E_JOBS_RUNTIME=1` and, in CI,
  `E2E_JOBS_CAPACITY=1`; capacity occupation requires a dedicated stack whose
  `RESOURCE_POOL_CPU` matches the seeded filler plan. Keep it separate from the
  `@workspace` lane and exclude `@jobs-runtime` from the general browser job.

## Work Guidance

- Keep the script a thin orchestrator over `nukelabctl` and the container
  engine. Add shared shell helpers to `scripts/lib.sh`, not here.
- Do not print tokens, env files, or full compose configuration. CI uploads
  Playwright reports, traces, and targeted container logs on failure only.
- CI browser jobs must keep `E2E_EXTERNAL_SERVER=1` and a fully started stack
  behind `BASE_URL`; combined tests are enabled with `E2E_COMBINED=1` and need
  the `VOLUME_BACKUP_*` helper/storage settings plus a helper-readable backup
  directory owned by UID 65532.
- Stop a running dev stack (`./nukelabctl dev stop`) before `start`; the dev and
  production stacks share container names and `nukelabctl start` refuses to run
  while the other mode is active.
- The workspace browser job builds `conda-base` and `workspace` and runs the
  `@workspace` tag before image publication.

## Verification

```bash
bash -n scripts/ci/e2e-stack.sh scripts/ci/jobs-drill.sh
shellcheck -x scripts/ci/e2e-stack.sh scripts/ci/jobs-drill.sh
shfmt -d scripts/ci/e2e-stack.sh scripts/ci/jobs-drill.sh
python3 -m py_compile scripts/ci/seed-jobs-fixture.py
```

The drill is opt-in: `.github/workflows/jobs-drill.yml` runs nightly and on
manual dispatch, never on the default pull-request path. Reproduce it locally
on a disposable host with
`./scripts/ci/jobs-drill.sh --build --stop` after preparing `.env`.

## Child NAD Index

- None
