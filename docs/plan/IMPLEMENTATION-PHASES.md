# Implementation Phases

This document records the original v2.0 implementation plan and current delivery status. Phases 1–5 and 7–10 are complete. Phase 6 (Kubernetes/production hardening) remains partially deferred.

**Last code review:** November 22, 2026. This review checked the capabilities below against the 2.3 release line; it did not rerun benchmarks or a production deployment. See [ROADMAP.md](ROADMAP.md) for the current capability gaps.

## Phase 1: Foundation & Scaffolding

**Status**: Complete ✅

- Monorepo structure (`frontend/`, `backend/`, `environments/`, `infrastructure/`, etc.)
- PostgreSQL schema, Alembic migrations, seed data
- Redis for sessions, pub/sub, Celery broker
- Local + NukeHub OAuth2 authentication
- NukeIDE containerization with nginx JWT proxy
- Basic container spawn/start/stop/delete lifecycle
- Traefik dynamic routing and WebSocket support

## Phase 2: User Management & RBAC

**Status**: Complete ✅

- Role and permission matrix
- User CRUD, profile, preferences
- NUKE currency ledger and daily allowance
- Admin dashboard with user/server/credit management

## Phase 3: Environment Templates & Resource Management

**Status**: Complete ✅

- Environment template CRUD (admin)
- Server plans with role and approval restrictions
- Per-user quotas and custom plans
- Resource pool tracking and queue-based scheduling
- Volume management and quota enforcement

## Phase 4: Real-Time Monitoring Dashboard

**Status**: Complete ✅

- Docker Stats metrics collection
- WebSocket streaming with Redis pub/sub
- Global, per-user, and per-server dashboards
- Alert rules and notification delivery
- Container health checks and auto-restart

## Phase 5: Advanced Platform Features

**Status**: Complete ✅

- Audit logging with export
- Server scheduling (cron + UI)
- Scoped API keys
- Shared workspaces
- Notification center (20+ types)
- Maintenance mode
- Two-layer rate limiting
- Operator database backup/restore (`scripts/manage.d/backup.sh`, `restore.sh`); owner-scoped offline private-volume backup/restore with a trusted helper, bounded storage and new-volume restores (`services/volume-helper/`, `volume_backup_service.py`)
- Bulk operations
- IP allowlist/blocklist
- CSRF protection and security headers
- Scheduled maintenance windows

## Phase 6: Production Hardening & Kubernetes

**Status**: Partial — Docker/Podman hardening and the 2.3.0 recovery/registry/supply-chain scope are implemented; automated deployment verification, remote-runner acceptance of the combined suite, external assessment, and Kubernetes remain open

### Completed

- OWASP Top 10 audit (`docs/security/OWASP-AUDIT.md`)
- Dependency scanning (`pip-audit`, `npm audit`, `bandit`)
- Security headers, path traversal prevention, production secret validation
- Database connection pooling, PgBouncer, query profiling
- Redis response caching
- Structured logging, Prometheus/Grafana, OpenTelemetry, Sentry
- CI/CD pipeline with GitHub Actions
- Load testing infrastructure
- Playwright browser specs, dual-mode configuration and disposable CI stack (`frontend/e2e/`, `frontend/playwright.config.ts`, `scripts/ci/e2e-stack.sh`); required unit/mocked/external/workspace CI jobs are wired into publishing
- Versioned core/environment image builds and GHCR publishing (`.github/workflows/ci.yml`)
- Pull-based deployment preparation, pre-migration database backups, and schema-compatibility guard (`scripts/manage.d/update.sh`, `db-migrate.sh`, `backend/app/db/schema_guard.py`)
- Crash-safe recovery: process/operation heartbeats, read-only evidence inspection, proof-backed finalization, bounded reconciliation, queue `starting` recovery, admin operations/queue consoles and owner recovery notifications (`operation_reconciliation.py`, `operation_finalizer.py`, `operation_reconciler.py`, `recovery_notifications.py`)
- Registry-verified environment revisions with exact platform-digest proof, optional digest pulls, portable fingerprint matching, and admin verify/revoke (`registry_artifact_service.py`, `environment_revision_admin_service.py`)
- Supply-chain gates: strict base-image pinning, weekly digest-drift review, and release-only deterministic CycloneDX SBOM plus build-provenance/SBOM attestations (`scripts/security/`, `.github/workflows/security.yml`, `.github/workflows/release.yml`)

### Deferred

- Kubernetes manifests and Helm chart
- Sealed Secrets / Vault integration
- Blue-green deployment automation
- Independent penetration assessment; internal findings and regression coverage already exist

### Remaining delivery gaps

- Remote-runner execution of the combined acceptance suite: the local disposable-stack combined and workspace suites pass; GitHub-hosted runs still provide the release evidence
- GitHub repository enforcement: `CI Gate`/`Security Gate` required checks, protected signed tags, and signed-commit enforcement are maintainer-owned settings
- Podman parity: registry pulls, hardening and crash recovery are verified on Docker 29.9.2; Podman remains untested
- Automated deployment health verification and traffic cutover: Future; `update` prepares images and instructs the operator to restart, and rollback is an operator procedure using a pinned image plus snapshot restore
- Scheduled base-image digest refresh: the weekly review opens or updates a tracked issue, but updating digests remains a reviewed pull request

## Phase 7: Production Hardening — Quick Wins

**Status**: Complete ✅

- Structured logging with correlation IDs
- HTTP request metrics
- Graceful shutdown coordinator
- Request size limits
- Strict CORS
- Database pooling and query timeouts
- Rate limiting (per-user + Traefik DDoS + WebSocket message throttling)
- Redis response caching with circuit breaker and stampede protection

## Phase 8: Load Testing & Performance Validation

**Status**: Complete — load-testing infrastructure delivered; current performance results were not revalidated in the November code review

- Locust + k6 hybrid setup
- Five test profiles: smoke, baseline, stress, spike, endurance
- PgBouncer connection-flood test
- Self-seeding test data
- Operational monitoring runbook

## Phase 9: Notification System Improvements

**Status**: Complete ✅

- Actionable notifications: every notification carries an `action_url` that
  routes the user to the relevant page (e.g. a credit-request conversation).
- Credit-request notifications deep-link requesters to
  `/settings/credits?request={id}` and reviewers to `/admin/credits?request={id}`.
- Bulk notification deletion (`POST /notifications/bulk-delete`) with
  scope-limited filters: by explicit ids, read-only, or all for the current user.
- Web Push delivery via VAPID keys and `pywebpush`, with subscription CRUD,
  dead-subscription cleanup on 404/410, and a service-worker `push` handler.
- Frontend notification row click-through, `/notifications` page bulk actions,
  and a settings push-notification toggle.

## Phase 10: Storage Monitoring

**Status**: Complete ✅

- Prometheus alerts for filesystem usage on the Postgres/Redis/volume backing
  store, Postgres database size growth (`pg_database_size_bytes`), and Redis
  memory usage (`redis_memory_used_bytes` / `redis_memory_max_bytes`).
- Grafana panels for Postgres database size, Redis used/max memory, and volume
  filesystem usage, configurable via a `node_exporter_rootfs_path` variable.
- Admin dashboard storage summary card exposing Postgres DB size, Redis memory,
  and volume filesystem usage through the existing `/api/admin/health/monitoring`
  endpoint, with short-lived caching.

## Known tech debt

- The combined frontend acceptance suite runs locally; remote-runner execution
  and flake observation remain release-verification work.
- Recovery inspection/finalization has unit and service coverage, but a
  real-stack worker-crash and helper-interruption exercise remains a release
  gate. Proof-backed reconciliation, admin reconcile and bounded reminders are
  implemented; there is no force path or time-based takeover.
- Registry verification and portable-fingerprint matching are implemented.
  Operator registry credentials/allowlists and retention of local-only artifacts
  remain deployment responsibilities.
- Automated deployment health verification and traffic cutover remain future
  work; rollback is operator-run with a pinned image plus snapshot restore, and
  tagged images, migration snapshots and the schema guard are in place.

Security findings live in [PENETRATION-TEST-FINDINGS.md](../security/PENETRATION-TEST-FINDINGS.md) and [PENETRATION-TEST-REMEDIATION.md](../security/PENETRATION-TEST-REMEDIATION.md).
