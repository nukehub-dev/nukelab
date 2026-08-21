# Scripts

## Purpose

`nukelabctl` dispatcher, shared shell library, build helpers, security scanners, and per-command modules that orchestrate the NukeLab stack.

## Ownership

All files under `scripts/`, plus the top-level `nukelabctl` dispatcher.

## Local Contracts

- Bash 4+; modules in `scripts/manage.d/*.sh` are sourced by the dispatcher, not executed directly.
- Tracked shell scripts (`nukelabctl`, `**/*.sh`) must be mode `100755` in the git index — prod pulls rely on it. Filesystems without Unix permissions (NTFS) record new files as `100644`; fix with `git update-index --chmod=+x <file>`. `selftest` enforces this. On such filesystems, invoke via `bash nukelabctl ...` when the on-disk exec bit cannot be set.
- `scripts/lib.sh` is the single source of truth for shared helpers (env loading, engine detection, state persistence, logging, venv provisioning).
- `init_env` exports `NUKELAB_VERSION` (from `_nukelab_version`, leading `v` stripped to match bare-semver image tags) when unset; `compose.yml` build args (`APP_VERSION`) consume it so locally built backend images report the checkout version. An explicit `NUKELAB_VERSION` in the environment or env file wins.
- `init_env` also exports `NUKELAB_IMAGE_TAG` (defaults to the pinned `NUKELAB_VERSION` in pull mode, or `latest` in source-build mode) and `NUKELAB_PULL_DEPLOY`. Setting `NUKELAB_VERSION` or `NUKELAB_IMAGE_TAG` explicitly switches `nukelabctl up` / `update` to pull pre-built images from `ghcr.io/nukehub-dev/nukelab-backend` and `-frontend` instead of building from source.
- `update` has a `--build` escape hatch that forces a source rebuild even when `NUKELAB_PULL_DEPLOY=true`. In source-build mode `update` and `pull` pull base images for the pullable infra services only, via `_pullable_infra_services`.
- `_pullable_infra_services` returns the pullable (non-buildable) infra services (`traefik postgres redis` + enabled overlay services) as a word-split list, mirroring `_backend_services`. App services (`backend`, `celery-worker`, `celery-beat`, `frontend`) are excluded so unpinned ghcr.io images are never pulled without registry auth; pull mode pulls them explicitly.
- Each management command exposes `cmd_<name>`, `help_<name>`, and `parse_<name>_args` when it accepts flags.
- Environment-file helpers live in `scripts/lib.sh`:
  - `load_env_file` exports active KEY=VALUE lines from a file.
  - `_read_env_into_assoc` reads active KEY=VALUE lines into an associative array without exporting.
  - `_assoc_has_key` tests associative-array key membership.
- `check-env` and `sync-env` compare local env files against `.env.example`.
  `check-env` is read-only; `sync-env` appends missing keys without overwriting
  existing values and never removes stale keys without operator consent.
- Security scanning helpers live in `scripts/security/`.

## Work Guidance

- 4-space indent; `case` labels indented; redirects spaced (`> /dev/null`); binary operators (`&&` / `||`) may start a line. `shfmt` enforces this via `.editorconfig`.
- Every `scripts/manage.d/*.sh` module starts with `#!/bin/bash` for shellcheck.
- Add new shared helpers to `scripts/lib.sh`; do not duplicate them across modules.
- Unknown flags must be rejected with `die "Unknown option for <cmd>: $arg"`; never silently swallow them.
- `set -E` ERR trap is active; append `|| true` when invoking tools that legitimately return non-zero (e.g., `shfmt -l`, `git describe`).
- `_acquire_lock` uses `flock` on a persistent fd (noclobber pidfile fallback); modules must not replace the dispatcher's EXIT/INT/TERM traps — lock cleanup chains through `_release_lock` from the existing traps.
- Do not hardcode the version string or names of named volumes/services; use `_nukelab_version` and `_backend_services`. Discover compose-managed volumes via the `com.docker.compose.project` label rather than hardcoded name prefixes.
- Release versioning: git tags (`vX.Y.Z`) are the source of truth. `scripts/bump-version.sh X.Y.Z` syncs `VERSION`, `frontend/package.json` + `frontend/package-lock.json` (via `npm version --no-git-tag-version`), and `CHANGELOG.md`; it never commits or tags. It deliberately does not touch `backend/app/version.py` — the backend version is dynamic (CI injects the image tag via the `APP_VERSION` build arg) and `version.py` is a fixed `0.0.0-dev` fallback.
- `_backend_services` returns a space-separated string meant to word-split; do not quote it at the call site (`# shellcheck disable=SC2086`).
- Environment build order matters: `manage.d/build.sh` builds `services/build-auth-sidecar.sh` before any `env base` build (base embeds the sidecar binary), then `conda-base`, then `workspace`/`dev`. `build-all.sh` mirrors that order. Keep the sidecar first when touching build orchestration.
- When adding or changing `nukelabctl` commands, targets, or flags, update
  `scripts/nukelabctl-completion.bash` so bash tab-completion stays in sync.
- `db-migrate` takes an automatic `pg_dump` snapshot before running
  `alembic upgrade head`. The snapshot is written to `backups/` with the name
  `pre-migrate-<NUKELAB_VERSION>-<current-revision>-<timestamp>.dump`. If the
  backup fails, the migration aborts. If the migration then fails, the exact
  `./nukelabctl restore <file>` command is printed. Use `--no-backup` to skip
  the snapshot when you have already arranged your own protection.

## Verification

```bash
./nukelabctl selftest
./nukelabctl lint shell
```

## Child NAD Index

- None
