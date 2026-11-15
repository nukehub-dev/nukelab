# NukeLab Roadmap

**Status**: Phases 1–5 and 7–10 delivered; phase 6 remains Partial. Docker/Podman hardening is implemented; launch readiness requires separate verification.

**Last Updated**: November 15, 2026

**Tech Stack**: Vite + React 19 SPA, FastAPI (Python 3.13), PostgreSQL 17, Redis, Traefik v3, Docker/Podman

The capability review below is based on repository inspection, not a fresh test run or live deployment. Release metadata currently declares v2.1.0; git tags remain the release source of truth.

## Recent milestones

- **System Config API** (`/api/system/config`, `/api/system/stats`)
- **Maintenance Mode** — Toggle platform on/off with 503 response
- **Audit Log Export** — CSV/JSON export (`/api/admin/activity/export`)
- **Rate Limiting** — slowapi integration and Traefik DDoS protection
- **Server Scheduling** — Cron-based schedules with visual builder UI
- **Shared Workspaces** — Volume sharing with member/invitation management
- **Notification Center** — In-app + email notifications with WebSocket delivery
- **Usage Trends** — Per-user and platform-wide historical charts (7d/30d/90d)
- **Permission Matrix Editor** — Full RBAC matrix UI
- **Bulk Operations** — Server start/stop/restart/delete; workspace activate/deactivate/delete; volume activate/archive/delete
- **Quick Spawn** — `Alt+N` opens deploy dialog pre-filled with saved user preferences
- **Default Spawn Preferences** — Settings UI for default plan + environment
- **Health Check Auto-Restart** — Rate-limited auto-restart for unhealthy containers
- **IP Allowlist/Blocklist** — Middleware + admin CRUD API + UI; CIDR support; self-block prevention
- **CSRF Double-Submit Protection** — Cookie/header pattern with smart exemptions
- **Security Headers (Exception-Safe ASGI)** — Injected even on 500 errors
- **Path Traversal Fix** — Centralized `secure_path()` utility
- **Production Secret Validation** — App refuses to start with default secrets
- **Structured Logging** — JSON/text formatters, correlation IDs, Celery propagation
- **HTTP Request Metrics** — `RequestMetric` model, route-aware normalization, batched writes, admin analytics
- **Graceful Shutdown** — `ShutdownCoordinator` with bounded timeouts
- **Request Size Limits** — 10 MB default with chunked-transfer abort
- **Strict CORS** — Explicit origin whitelist, preflight caching, rejects `*` with credentials
- **Redis Response Caching** — msgpack serialization, circuit breaker, stampede protection, SET invalidation
- **OpenTelemetry Distributed Tracing** — End-to-end across FastAPI, Celery, SQLAlchemy, Redis
- **CI/CD Pipeline** — GitHub Actions lint/test/build/push, path-filtered
- **Load Testing** — Locust/k6 hybrid, five profiles, PgBouncer connection flood
- **NVIDIA GPU Support** — Plan-based GPU passthrough (Podman CDI / Docker DeviceRequests), quota accounting, GPU metrics, CUDA environment image (`docs/operations/GPU-SETUP.md`)
- **Exclusive GPU Allocator** — Whole-GPU reservations (`gpu_allocations`) with race-safe booking and recreate-on-start (`GPU_DEVICES`)
- **Container Runtime Driver Layer** — `ContainerDriver` ABC with Docker/Podman as the first driver (`CONTAINER_RUNTIME`); prepares the k3s/Kubernetes migration
- **Pull-based Production Deploys** — Pin `NUKELAB_VERSION` or `NUKELAB_IMAGE_TAG` to deploy tagged `ghcr.io/nukehub-dev/nukelab-backend` / `-frontend` images without rebuilding from source
- **Notification Improvements** — Action links, bulk deletion, and Web Push delivery (phase 9)
- **Storage Monitoring** — Postgres, Redis, and volume storage summaries, alerts, and dashboards (phase 10)
- **Environment Image Publishing** — CI builds/version-tags/publishes base, conda-base, workspace, and dev images to GHCR
- **Upgrade Recovery Foundations** — Pre-migration database snapshots and backend schema-compatibility guard

See [IMPLEMENTATION-PHASES.md](IMPLEMENTATION-PHASES.md) for the full phase-by-phase record.

## Model highlights

- **ServerPlan** — `max_runtime`, `idle_timeout`, `allow_scheduling`, `allow_snapshots`
- **Server** — `health_status`, `health_check_config`, `last_health_check`, `status_reason`, `stopped_by`, `stop_reason`
- **ServerQueue** — `requested_cpu`, `requested_memory`, `requested_disk`

## Verification status

- Backend tests are wired into CI; test counts and current pass rates were not revalidated in this review.
- Frontend unit tests and Playwright specs exist. `.github/workflows/ci.yml` currently runs frontend lint/format/build, with no frontend test job.
- Load-test tooling exists; its presence does not establish current production capacity.

## Capability review

| Capability | Status | Implemented evidence | Remaining scope |
| --- | --- | --- | --- |
| Environment image build/publish | Complete | `.github/workflows/ci.yml`, `scripts/ci-version.sh` | Scheduled base-image digest refresh and scientific image validation are separate follow-ups; scientific image ownership is in the separate environments repository |
| Reproducible environments | Partial | Approved revision/launch models, strict manifest schema, `environment_revision_service.py`, `server_provenance_service.py`; existing driver composition | Integrate immutable image resolution/caches and launch capture; expose export/recreate API/UI; runtime verification |
| Database backup/restore | Complete | `scripts/manage.d/backup.sh`, `restore.sh`, `db-migrate.sh`; backend schema guard | Automated recovery drills and broader disaster-recovery policy |
| User volume backup/restore | Partial | `VolumeBackup` scaffolding plus durable `volume_operation_service.py` and bounded `volume_archive_service.py` extraction foundation | Backup capture/storage/retention, runtime helper and attachment checks, all writer/start guards, API/tasks/UI; recovery remains unavailable |
| Resource queue experience | Partial | Durable request/claim fields, typed queue DTOs, transaction-owned queue primitives, corrected deterministic positions, configured resource budgets | Replace legacy launch/worker integration; register the owner queue router only after claims/cancellation are respected; user queue UI and GPU-aware waiting |
| Batch scientific jobs | Future | Existing schedules support server start/stop/restart; Celery runs platform tasks | User command submissions, job records, exit status, logs, artifacts, retries, and parameter sweeps |
| Workload secrets | Future | Platform signing keys, OAuth token encryption, and template environment variables already exist | Scoped credential storage, authorization, redaction, and workload injection; template variables are ordinary JSON, not a secret store |
| Deployment automation | Partial | Tagged pulls, explicit restart workflow, migration snapshots, schema guard | Automated health verification, traffic cutover, and rollback; zero-downtime deployment is not implemented |
| Browser end-to-end tests | Partial | `frontend/e2e/`, Playwright config, `scripts/manage.d/e2e.sh` | Execute against an isolated stack in CI; run frontend unit tests in CI too |
| Independent penetration assessment | Future | Internal findings, remediation records, security regression tests, and scan workflow exist | External assessment and retest before public launch |

## Current priorities

Queue reliability, reproducible environments, private offline volume recovery, and frontend test CI are accepted implementation scope. Backend foundations are present; the end-to-end workflows remain incomplete.

1. **Finish existing workflows (In Progress)** — Integrate atomic launch/queue admission and add a queue view/cancellation; wire existing frontend tests into CI.
2. **Research reproducibility (In Progress)** — Persist resolved image/toolchain identities and provide export/recreate; extend existing composition rather than rebuilding image publishing.
3. **Research data recovery (In Progress)** — Deliver user volume backup/restore and verify database recovery through isolated drills.
4. **Batch jobs** — Add a minimal command-based job lifecycle, then parameter sweeps after single jobs are reliable.
5. **Scoped workload secrets** — Separate credentials from ordinary template configuration; choose the storage/integration approach during design.
6. **Public-launch readiness** — Independent penetration assessment and a verified deployment/recovery procedure.

## Deferred goals

- **Deferred:** Kubernetes migration (Helm, HPA, PVCs, Network Policies, Pod Security Standards)
- **Deferred:** Blue-green traffic cutover and automatic rollback; existing tagged-image deployment and database recovery foundations are already implemented
- **Deferred:** Marketplace / plugin system
- **Deferred:** Vault / sealed-secrets integration; workload secret requirements should be established before choosing an integration

Pursue Kubernetes only after saturating a single large server (32+ cores, 128GB+ RAM) and proving distribution is required.

## Decision log

See [DECISION-LOG.md](DECISION-LOG.md).
