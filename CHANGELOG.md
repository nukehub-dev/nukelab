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

- Owner single-run batch jobs (pilot): submit one noninteractive command against
  an eligible CPU plan and an owned private volume, with queued, running,
  cancellation, recovery, result, and bounded-log views at `/jobs` and
  `/jobs/{id}`. Zero-cost plans are always available; paid plans are gated.
  Submissions are opt-in and JWT-only.
- A durable batch-job journal (`batch_jobs`, `batch_job_logs`) with idempotent
  submission, fenced admission, shared CPU/memory/disk accounting, owner/fleet
  caps, and an exclusive `job_writer` volume guard. Job history, retained logs,
  and cancellation remain available while submission is disabled.
- A faster batch-job form: searchable environment, plan, and private-volume
  pickers; a link to `/volumes` with list refresh for creating a work volume;
  second/minute/hour runtime units with a one-minute minimum; and all active
  CPU plans listed with paid plans disabled and explained while paid jobs are
  off. Long select labels now wrap instead of creating horizontal scroll.
- A hardened headless execution profile: approved immutable image identity,
  owned `/work` preparation before the non-root job, literal argv with no shell
  parsing, no network, read-only rootfs, dropped capabilities, UID 65532, bounded
  runtime and logs, and create/start checkpoints with bounded monitor, cleanup
  retry, and recovery inspection.
- Guided first launch on the dashboard and deploy dialog: eligible current
  catalog defaults are preselected, stale saved plan/environment defaults are
  surfaced instead of submitted, and catalog failures no longer look like a
  missing catalog.
- Sanitized cross-owner batch-job visibility at `/admin/jobs` with state,
  reason, owner/environment/plan/volume labels, reservation and volume-guard
  flags, heartbeat age, and log/cleanup state. Jobs-specific `jobs:read_all`,
  `jobs:write_all`, and `jobs:access_others` grants mirror the server
  cross-owner model; legacy Operations grants remain a compatibility fallback.
  Operators with manage authority get a reason-audited safe cancel for
  queued/starting/running rows and a proof-only reconcile action for
  `recovery_required` rows. Cancel releases a queued job's full hold but never
  force-releases a started job's reservation, volume guard, or hold; ambiguous
  reconcile evidence returns 409 and releases nothing.
- Bounded physical purge of expired batch-job log payloads and one deduplicated
  owner completion notification per terminal result. Purge preserves the
  terminal result and metadata; notification failure never changes the result or
  releases protection.
- A read-only storage-enforcement capability probe. Capabilities report whether
  the configured volume storage path has kernel-enforced XFS project quotas, and
  `BATCH_JOBS_REQUIRE_STORAGE_ENFORCEMENT=true` fails submission/admission closed
  instead of advertising an unenforced writable limit.
- An explicit `@jobs-runtime` real-stack browser gate, a disposable fixture
  seeder, and an opt-in worker/broker interruption drill workflow.
- Paid batch jobs (gated): with `BATCH_JOBS_ALLOW_PAID_PLANS=true`, an eligible
  nonzero-cost plan freezes its hourly rate, creates one spendable-credit hold
  for the maximum runtime, and settles actual runtime at terminal proof. Unused
  authorization is refunded; a 1-NUKE minimum applies only after the job starts.
  Queued cancel/expiry and pre-start failures release the full hold.
- `credit_holds` with one authorization per paid job, `batch_job_usage` ledger
  entries, and owner-facing hold/charged/refunded state. Batch job usage is
  labeled in owner and admin credit history.
- `./nukelabctl doctor --post-upgrade` verifies a running deployment read-only:
  service containers, public API health and release version, image identity,
  Alembic head compatibility, Celery worker/Beat presence, unresolved recovery
  rows, and optional batch-job tables.
- Batch-job recovery metrics for queued, active, recovery-required, and
  cleanup-pending rows.

### Changed

- Batch dispatch, execution, monitoring, recovery, and expired-log purge run
  from `celery-worker`/Beat with configurable bounded intervals. Active batch
  reservations participate in the existing resource-pool and quota accounting.
- Volume mutation, backup/restore, mount intent, and deletion now share the
  `job_writer` exclusive guard, so a job's `/work` volume cannot change while
  the runtime outcome is unresolved.
- The admin Jobs table keeps long owner/environment labels inside their columns
  instead of overlapping protection evidence, with a browser layout regression.
- Interactive launch, restart/resume, periodic server billing, and reconciliation
  now use spendable balance (total balance minus active batch-job holds), so
  interactive usage cannot consume credits reserved by a queued or running paid
  job.

### Security

- Owner job routes require JWT and `jobs:read_own`/`jobs:write_own`; foreign job
  IDs return 404. Admin job rows require a JWT session plus `operations:read_all`
  and `ADMIN_ACCESS`, and never expose argv, logs, environment values, image
  references, volume paths, runtime identity, or fencing tokens. Proof-only
  reconcile additionally requires `operations:manage_all`, a bounded reason, and
  a successful audit write; there is no force or manual-release path.
- Batch containers run without network access, ports, capabilities, rootfs
  writes, restart policy, or platform credentials. Argument count/bytes, runtime,
  pids, memory, tmpfs, and log output are bounded; terminal release requires
  termination proof.
- Paid submission creates one hold under the admission and user locks, rejects
  insufficient spendable balance with 402 and no rows, and is idempotent. Foreign
  owners cannot read or release another owner's hold. Terminal settlement writes
  at most one `batch_job_usage` transaction; `recovery_required` retains the hold
  until proof-backed reconciliation. Settlement never changes or rolls back a
  terminal result.

### Deferred

- Batch submission remains disabled by default for the pilot, and paid plans
  remain off until `BATCH_JOBS_ALLOW_PAID_PLANS=true` is explicitly set. Paid
  access follows plan visibility; restrict the paid plan to the intended role or
  cohort.
- The new explicit real-stack CI browser job and the nightly interruption-drill
  workflow have not yet run on a GitHub runner. No staging pinned upgrade,
  rollback, off-host restore, or registry `preload_only` rehearsal has completed.
- The real-stack zero-cost and paid jobs, worker/broker interruption drills, and
  last-slot/volume race suites passed locally on a disposable Docker stack. An
  actual over-cap write on XFS project-quota storage still needs target-storage
  evidence; the current host reports unenforced storage.
- Podman job enablement and scoped workload secrets remain pending. Paid access
  is a gated pilot, not a general release default.

### Verification

- Backend full suite passed: 5,122 passed, 6 skipped, 0 failed.
- Frontend unit tests (247), lint, format check, type check, and production build
  passed.
- Targeted mocked browser suites passed: jobs UI 14, guided first launch 9, admin
  jobs UI 13, and the existing queue/admin-setup regressions 10.
- A real API→PostgreSQL/Redis/Celery/Docker `@jobs-runtime` scenario passed on a
  rebuilt disposable stack: capacity queueing, one hardened runtime (UID 65532,
  read-only rootfs, `CapDrop=ALL`, no network, no ports, no restart), output and
  bounded logs, nonzero exit, cancellation, owner isolation, and cleanup.
- Worker-death and Redis-broker-loss interruption drills passed with one job row,
  one create, one start, one terminal result, one released guard, zero negative
  credit transactions, and cleanup complete.
- A real paid job passed on the same stack: a 2-NUKE hold was visible while
  queued/running, actual runtime settled at 1 NUKE, the unused 1 NUKE was
  refunded, and exactly one `batch_job_usage` ledger entry was written.
- Storage capability and last-slot/volume race suites passed; the host storage
  root is not kernel-enforced, so the over-cap write remains a target-storage
  gate. Shell lint, `docker compose config -q`, and `./nukelabctl selftest`
  passed.

## [2.3.0] - 2026-11-22

### Added

- Crash-safe recovery foundation: per-process worker heartbeats with container
  incarnation identity, fenced operation heartbeats, and active approval reuse.
  Heartbeat age is an inspection trigger only; it never releases reservations
  or proves termination by itself.
- Registry-verified environment identity: bounded OCI/Docker registry
  resolution with Bearer/Basic authentication, exact platform manifest digest
  proof, optional registry-verified pulls, and a portable environment
  fingerprint for cross-install matching. Tag movement never creates a new
  approval automatically.
- A range-scoped signed-commit check for pull requests, pushes and release
  tags, so legacy unsigned history does not block new work.
- Cross-install environment manifests now match destination approvals by the
  portable fingerprint only; local-only manifests keep strict local revision
  matching. Admin operations visibility adds sanitized list/detail views and a
  proof-only reconcile action with no force path.
- `doctor` now reports recovery-journal, heartbeat, registry-verification,
  credential, and legacy-row state without mutating the stack.
- External Dockerfile base images are now checked by a strict `Base Image
  Pinning` security job included in `Security Gate`; a weekly review reports
  upstream tag drift in one tracked issue.
- Tagged release CI publishes deterministic CycloneDX SBOMs plus build
  provenance and SBOM attestations for every image, then verifies them with
  `gh attestation verify`. Normal branch CI does not run the release-only
  scans.
- Operators get a read-only cross-owner queue view, and owners get deduplicated
  recovery attention/completion notifications plus a bounded daily reminder
  for unresolved recovery-required work. Queue rows include sanitized
  owner/environment/plan names, requested resources and status summaries; the
  owner filter uses a directory picker when the operator can read users.
- Recovery operations show sanitized target and owner names, and environment
  revision history supports loaded-page portability/revocation filters, search,
  and copyable full IDs, fingerprints and manifest digests.
- Recovery metrics and alerts cover worker-heartbeat freshness, recovery-scan
  health, stalled or recovery-required operations, and registry-verification
  gaps. Scan freshness is persisted so the backend scrape reports work that ran
  in the Celery process.
- Queue `starting` requests are mapped to their launch operation. An orphaned
  request stays operator-visible until runtime absence is proved, and work is
  never blindly requeued or cancelled.
- A backup artifact cleanup interrupted after its durable `delete:<uuid>` claim
  is recovered only after the claimant is proven stopped; the retry rechecks
  mounts and either removes the artifact or records `delete_failed`.
- Volume backup/restore execution now heartbeats under its fenced operation,
  and proof-backed completion is applied by the reconciler only after artifact
  and helper-termination checks. The admin UI adds environment-revision and
  recovery-operation consoles; the console has no force or override path.
- A launch left `uncertain` by a crash may be adopted as success only when
  complete runtime and public-readiness proof is available; otherwise it stays
  protected for operator reconciliation.

### Changed

- Mobile page content and the bottom navigation dock respect iOS safe-area
  insets, so the last controls remain scrollable above the dock.
- Recovery scans now use partial indexes matching the active launch, backup and
  restore selection order. On a 100k/50k/50k seeded journal the three-query
  p95 dropped from 16.9 ms to 2.4 ms, so the 30-second scan no longer reads
  completed history.
- The root README architecture map is now a generated light/dark SVG pair
  selected by `<picture>`, with local brand icons embedded as data URIs and no
  CDN or runtime network dependency. The old HTML/PNG source was removed and
  docs CI verifies the generated SVGs against their checked-in generator.

### Security

- Updated the frontend nginx base to 1.31.9 with Alpine package upgrades, moved
  the shared environment base to Debian 13.7 and require
  `nginx >= 1.26.3-3+deb13u11`, and rebuilt the auth sidecar with Go 1.27.4.
  This picks up the nginx2root and related DSA-6642-1 fixes (CVE-2026-123007,
  CVE-2026-123633, CVE-2026-121810, CVE-2026-123634, CVE-2026-113425,
  CVE-2026-118899) plus current Go standard-library fixes.
- Upgraded Traefik from the end-of-life 3.6 line to 3.7.19, including fixes for
  the HTTP/1 opaque request-target routing/auth bypass, CONNECT connection-pool
  poisoning, and ReplacePathRegex traversal advisories. Enabled
  `global.aliasHeadersStrategy: delete` and bounded monitoring ForwardAuth
  response bodies.
- Refreshed frontend lockfile dependencies to clear all `npm audit` findings,
  including the seroval deserialization issue.
- Updated the backend runtime base to Python 3.13.18 on Debian 13.7, PyJWT
  2.14.0, and msgpack 1.2.3, and removed the unused pip/setuptools tools from
  shipped backend and volume-helper images. Trivy now reports no fixed
  HIGH/CRITICAL vulnerabilities in either image.

## [2.2.0] - 2026-11-20

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
