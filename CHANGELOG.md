# Changelog

All notable changes to the NukeLab platform are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Releases are cut with `scripts/bump-version.sh X.Y.Z`, which stamps the
`[Unreleased]` section below and syncs the version across `VERSION`,
`frontend/package.json`, and `frontend/package-lock.json`. Git tags (`vX.Y.Z`)
are the release source of truth; CI builds container images tagged with the
release version and drafts a GitHub Release from the matching changelog
section.

## [Unreleased]

### Added

- Required frontend test CI: Vitest units, Vite-only account-switch specs, a
  disposable real-stack browser suite (including direct gateway access), and the
  workspace/IDE gateway image job now block image publication. The browser jobs
  build the real base runtime, approve A/B fixture images, publish Playwright
  failure artifacts and clean up only their own stack resources.
- A combined real-stack acceptance scenario covers approved environment A, an
  offline private-volume backup and restore into a new volume, queued recreation
  with a capacity wait, owner/privacy checks, actual runtime identity, restored
  file hashes and a corrupted-artifact failure drill.
- The trusted volume helper is built, scanned, version-tagged and published as
  `ghcr.io/nukehub-dev/nukelab-volume-helper`; `pull`/`update` fetch an explicitly
  configured remote helper image.
- Owner-scoped offline private-volume backups and restore into new private volumes,
  with bounded storage, retention, protected recovery history and capability-gated UI.
  Requires an operator-configured private artifact bind and trusted local helper image.
- Saved launch provenance and sanitized environment export, with owner recreation
  and manifest import through currently approved revisions, plans and explicit
  volume choices. The UI shows the last verified launch and local-only limits.
- Owner-scoped waiting requests with typed queued acceptance, capability-gated
  queue polling, pending cancellation and duplicate-request navigation.
- Dashboard first-run guidance for users without servers, with a direct link
  that opens the deploy flow instead of leaving new users to find it.
- Admin first-run `/admin/setup` checklist for publishing an active public
  environment, making plans available to users and testing the first launch.
  Dashboard and deploy dialogs now show truthful prerequisite states when the
  catalog is incomplete.
- Fresh installs seed Small/Medium/Large plans visible to the `user` role;
  XLarge remains admin-only. Re-seeding never overwrites admin edits.
- Durable fenced lifecycle operations for start, restart, resize, stop and delete;
  pinned launch generations and reservations survive uncertain runtime outcomes.
- Shared launch orchestration reserves server, GPU and volume-mount identities
  before provisioning, with pinned runtime/toolchain artifacts and bounded queue
  dispatch selected by creation APIs and queue workers.
- Immutable toolchain cache preparation verifies artifact, platform and layout;
  live caches are never repopulated and uncertain helpers retain their locks.
  An opt-in isolated container test rehearses tag replacement while a reader
  keeps the original cache mounted.
- Backend foundations for durable queue requests, approved environment revisions,
  launch provenance, transaction-owned admission, and exclusive volume operations.
- Bounded archive validation and extraction into fresh destinations, with checksum,
  path/link, metadata, expansion and ownership checks.
- Configurable allocatable CPU, memory and disk budgets and queue policy settings.

### Changed

- The new waiting-request, environment-provenance and volume-recovery surfaces
  now follow the platform's bubble cards, semantic status pills, compact
  metadata, responsive drawers and mobile layouts.
- Volume recovery history uses full-width Backups/Restores tabs, opens
  restore-only volumes on Restores and avoids duplicating the summary grid.
- Plan administration now refuses to remove the last active plan, or the last
  active plan available to users, so the catalog cannot be made un-deployable.
  Admins can still edit resources, pricing, names and other plan fields.

### Fixed

- Notification toasts deduplicate by notification id and suppress recent replay
  on shell remounts, so queue/usage/volume page switches no longer repeat the
  same server-start event.
- Admin deep links and refreshes wait for the first profile fetch instead of
  redirecting to the dashboard while the persisted auth store is still empty.
- `./nukelabctl restore` accepts `--stamp <revision>` so a pre-migration rollback
  snapshot is stamped with the previous release's Alembic head instead of the
  running image's head. Compose now passes `DB_SCHEMA_GUARD` from `.env`.
- Queue-, schedule- and health-admitted servers now receive the same container
  hardening, server-auth, public URL and runtime settings as API-created
  servers; the Celery worker no longer silently spawns unhardened runtimes.
- A newly created empty private volume selected by a launch is initialized for
  the non-root runtime once; existing data volumes keep their permissions.
- Read-only runtime root filesystems provide a writable `/home`, so servers that
  mount only explicit data volumes can start.
- Recovery attachment/artifact checks ignore trusted platform containers that
  bind the private storage root, so child volumes can detach and retained
  backups can be deleted.
- Traefik is upgraded to a release compatible with Docker Engine 29's minimum
  API version, and Kombu is pinned to the version compatible with the pinned
  redis-py.
- Frontend permission evaluation now expands `*_read_all`/`*_write_all` grants
  into their owner-scoped implications, matching backend RBAC so admins can use
  queue, provenance and recovery controls, while a wildcard grant still covers
  future permissions.
- Admin bulk server actions now require server-write authority, a cross-user
  reason and the shared audit/notification path; they no longer bypass the
  owner bulk authorization contract.
- Offline server edits initialize newly selected empty volumes for the hardened
  runtime and refresh plan allocations and quota usage immediately.
- Runtime volume data ignores no longer hide volume API regression tests.
- Backup retention skips active restore pins and unsupported artifacts before
  applying its batch limit, so older pinned copies cannot block later cleanup.
- Recreation preview requires read and manage permissions/scopes so management
  tokens cannot read saved manifests through a metadata preview.
- Data mounts cannot shadow platform security paths or approved toolchain roots.
- Home-volume sharing warnings survive lifecycle edits and server deletion;
  resumed legacy mounts retain their usage history.
- Delayed runtime status reads cannot overwrite a newer lifecycle reservation.
- Queue scans rotate through bounded batches so an early non-fitting batch does
  not permanently hide later requests.
- Queue positions now use deterministic priority ordering and return no position
  for missing or terminal requests.
- Fresh runtime drivers close partially initialized clients after connection failure.
- Lint commands now propagate backend and frontend tool failures out of their
  subshells, including `--fix`, so later successful checks cannot mask failures.
- The CPU-mask write-open regression compares native kernel behavior with and
  without the library, allowing the test to run correctly as root in containers.

## [2.1.0] - 2026-08-22

### Added

- Pull-based production deploys: pin `NUKELAB_VERSION` or `NUKELAB_IMAGE_TAG`
  to switch `nukelabctl start` / `update` from source builds to pulling tagged
  `ghcr.io/nukehub-dev/nukelab-backend` and `-frontend` images. The three
  backend services share one backend image; `update --build` forces a source
  rebuild even in pull mode. Unpinned deploys keep today's source-build
  behavior.
- Release versioning: git tags (`vX.Y.Z`) are the single source of truth.
  `scripts/bump-version.sh` syncs `VERSION`, `frontend/package.json`,
  `frontend/package-lock.json`, and this changelog. The backend version stays
  dynamic through `APP_VERSION`; `backend/app/version.py` remains the
  `0.0.0-dev` fallback.
- Dynamic version injection: CI image builds pass the resolved tag as the
  `APP_VERSION` build arg (`backend/Dockerfile`), so running containers
  report the exact image tag (`2.1.0`, `main`, `pr-42`). The API root,
  `/health/status`, and the OpenTelemetry service version resolve via
  `settings.app_version`; empty or unset `APP_VERSION` falls back to the
  static literal in `app/version.py`.
- Compose builds bake the platform version into locally built backend images:
  `nukelabctl` exports `NUKELAB_VERSION` (from the `VERSION` file / git tag,
  overridable via the env file) and `compose.yml` passes it as the
  `APP_VERSION` build arg to the backend and celery images, so stacks
  deployed with `nukelabctl` report the checkout version instead of
  `0.0.0-dev`.
- Automatic pre-migration backups: `./nukelabctl db-migrate` now takes a
  `pg_dump` snapshot before running `alembic upgrade head`. The snapshot name
  is `backups/pre-migrate-<NUKELAB_VERSION>-<current-revision>-<timestamp>.dump`.
  If the backup fails, the migration aborts; if the migration then fails, the
  exact `./nukelabctl restore <file>` command is printed. Use `--no-backup` to
  skip the snapshot.
- Startup schema-compatibility guard (`app/db/schema_guard.py`) refuses to boot
  an old backend image against a newer database schema. Controlled by the
  `DB_SCHEMA_GUARD` setting (`auto` refuse in production/warn elsewhere,
  `enforce` always refuse, `off` disabled). If the database is unreachable the
  guard logs a warning and does not block startup.
- Environment-file drift detection and repair: `./nukelabctl check-env` compares
  `.env` / `.env.development` against `.env.example` and reports missing or
  stale keys (optionally value differences with `--changed`, all files with
  `--all`). `./nukelabctl sync-env` non-destructively appends missing keys from
  `.env.example` while preserving existing local values and secrets; stale keys
  are reported but left for manual removal. Both commands are read-only by
  default unless `sync-env` is invoked with `--yes` or confirmed interactively.
- Production version guard: when `APP_ENV=production`, `nukelabctl` refuses to
  boot if the resolved version is `0.0.0-dev`. Production requires a real
  release via `VERSION`, a git tag, or an explicit `NUKELAB_VERSION` /
  `NUKELAB_IMAGE_TAG` (the latter is useful when pulling pre-built GHCR
  images).

### Changed

- Backend version string is no longer hardcoded: `app/main.py`,
  `app/api/health.py`, and the OpenTelemetry service version in
  `app/config.py` all resolve through `settings.app_version` (env-first,
  static fallback in `app/version.py`).
- The static fallback in `app/version.py` is now the fixed sentinel
  `0.0.0-dev` instead of a release-looking literal — a version that can
  never be mistaken for a release, and which `bump-version.sh` no longer
  touches (only `VERSION`, `frontend/package.json` + lockfile, and this
  changelog are bumped at release time).
- `frontend/package.json` version set from `0.0.0` placeholder to the
  platform version.

### Fixed

- CI/CD workflow now triggers on `v*.*.*` tags and builds/pushes release
  images when a tag is pushed, including platform environment images
  (`nukelab-environment-base`, `nukelab-environment-conda-base`, `nukelab-environment-workspace`, `nukelab-environment-dev`).
  The `build-images` job and per-matrix `Build and push` step both run for tag
  pushes regardless of path-filter results, and the path-filter `any` rule is
  updated so version-only changes trigger builds. A new `Release` workflow
  creates a draft GitHub Release from the matching `CHANGELOG.md` section and
  appends the published container image references.

## [2.0.0]

The 2.0 platform was delivered phase-by-phase without git tags. See
[docs/plan/IMPLEMENTATION-PHASES.md](docs/plan/IMPLEMENTATION-PHASES.md)
for the full delivery record and [docs/plan/ROADMAP.md](docs/plan/ROADMAP.md)
for recent milestones.
