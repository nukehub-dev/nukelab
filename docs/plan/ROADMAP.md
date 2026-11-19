# NukeLab Roadmap

**Status**: Phases 1–5 and 7–10 delivered; phase 6 remains Partial. Docker/Podman hardening is implemented; launch readiness requires separate verification.

**Last Updated**: November 19, 2026

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
- **Environment Image Publishing** — CI builds/version-tags/publishes base, conda-base, workspace, dev and volume-helper images to GHCR
- **Frontend Test CI** — Required Vitest, Vite-only mocked-browser, disposable real-stack and workspace/IDE browser jobs block image publication
- **Combined Recovery Acceptance** — A real-runtime Playwright scenario covers approved provenance A, offline volume backup/restore, queued recreation with capacity wait, owner privacy, identity checks and a corrupted-artifact failure drill
- **Upgrade Recovery Foundations** — Pre-migration database snapshots and backend schema-compatibility guard
- **Admin Catalog Setup** — `/admin/setup` first-run checklist, user-visible seeded plans, last-plan safety guard, and truthful dashboard/deploy prerequisite states

See [IMPLEMENTATION-PHASES.md](IMPLEMENTATION-PHASES.md) for the full phase-by-phase record.

## Model highlights

- **ServerPlan** — `max_runtime`, `idle_timeout`, `allow_scheduling`, `allow_snapshots`
- **Server** — `health_status`, `health_check_config`, `last_health_check`, `status_reason`, `stopped_by`, `stop_reason`
- **ServerQueue** — `requested_cpu`, `requested_memory`, `requested_disk`

## Verification status

- Backend unit/service/API tests and the coverage floor are wired into CI. Real daemon fixtures are separately opt-in with `--run-container-integration`; their presence does not establish browser or production acceptance.
- Frontend CI runs Vitest plus the required Vite-only mocked-browser, disposable real-stack and workspace/IDE gateway browser jobs; the combined provenance/recovery/recreation acceptance run is enabled with `E2E_COMBINED=1`. Image publishing depends on those checks.
- The combined provenance/offline-recovery/queued-recreation scenario passes against a local disposable Docker stack. Remote GitHub Actions runner validation and worker-crash reconciliation remain release gates.
- Load-test tooling exists; its presence does not establish current production capacity.

## Capability review

| Capability | Status | Implemented evidence | Remaining scope |
| --- | --- | --- | --- |
| Environment image build/publish | Complete | `.github/workflows/ci.yml`, `scripts/ci-version.sh` | Scheduled base-image digest refresh and scientific image validation are separate follow-ups; scientific image ownership is in the separate environments repository |
| Reproducible environments | Partial | Approved immutable revisions/caches and verified generations; capability-gated provenance, sanitized export, validated source/import recreation APIs and owner UI; combined real-runtime acceptance suite | Verified registry portability, cross-installation approval matching and remote CI validation |
| Database backup/restore | Complete | `scripts/manage.d/backup.sh`, `restore.sh`, `db-migrate.sh`; backend schema guard | Automated recovery drills and broader disaster-recovery policy |
| User volume backup/restore | Partial | Owner-scoped offline private-volume admission/API/tasks/UI, bounded helper capture/restore, retention, restore pins and writer exclusion (`volume_backup_service.py`, `volume_recovery_runtime.py`, `services/volume-helper/`); combined real-stack restore and corrupt-artifact drill | Remote CI validation, worker-crash reconciliation and operator storage/helper configuration |
| Resource queue experience | Partial | Typed 202 acceptance, atomic API/worker admission, owner queue UI/cancellation, GPU-aware waiting and rotating bounded dispatch; combined real-stack queued recreation/cancellation acceptance | Remote CI validation and worker-crash reconciliation rehearsal |
| Batch scientific jobs | Future | Existing schedules support server start/stop/restart; Celery runs platform tasks | User command submissions, job records, exit status, logs, artifacts, retries, and parameter sweeps |
| Workload secrets | Future | Platform signing keys, OAuth token encryption, and template environment variables already exist | Scoped credential storage, authorization, redaction, and workload injection; template variables are ordinary JSON, not a secret store |
| Deployment automation | Partial | Tagged pulls, explicit restart workflow, migration snapshots, schema guard | Automated health verification, traffic cutover, and rollback; zero-downtime deployment is not implemented |
| Browser end-to-end tests | Partial | `frontend/e2e/`, dual-mode Playwright config, `scripts/ci/e2e-stack.sh`, required unit/mocked/external/workspace CI jobs and combined acceptance suite | Remote GitHub Actions runner validation and flake observation |
| Independent penetration assessment | Future | Internal findings, remediation records, security regression tests, and scan workflow exist | External assessment and retest before public launch |

## Current priorities

Queue reliability, reproducible environments, private offline volume recovery, and frontend test CI are accepted implementation scope. Queue, approved recreation and offline private-volume recovery have application flows and a combined real-stack acceptance suite; remote CI execution, crash reconciliation and release preparation remain.

1. **Finish existing workflows (In Progress)** — Exercise the required browser jobs on remote CI, then verify worker-crash reconciliation and release gates.
2. **Research reproducibility (In Progress)** — Add verified registry portability and cross-installation approval; extend existing composition rather than rebuilding image publishing.
3. **Research data recovery (In Progress)** — Verify database recovery and worker interruption through isolated drills.
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
