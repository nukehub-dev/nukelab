# NukeLab Roadmap

**Status**: Phases 1–5 and 7–10 delivered; phase 6 remains Partial. The 2.3.0 recovery, registry-verification and supply-chain scope is implemented; recovery exercise coverage and public-launch gates remain separate.

**Last Updated**: November 22, 2026

**Tech Stack**: Vite + React 19 SPA, FastAPI (Python 3.13), PostgreSQL 17, Redis, Traefik v3, Docker/Podman

The capability review below is based on repository inspection, not a fresh test run or live deployment. Git tags remain the release source of truth.

## Recent milestones

- **2.3.0 recovery and registry line** — process/operation heartbeats, read-only evidence inspection, proof-backed reconciliation, admin operations and queue consoles, owner recovery notifications, registry-verified revisions with portable fingerprints, strict base-image pinning, weekly digest-drift review, and release SBOM/provenance attestations
- **2.2.0 Release** — Durable queue requests, saved launch provenance and approved recreation, offline private-volume backup/restore, and required frontend browser CI
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
- **EnvironmentRevision** — `fingerprint`, `portable_fingerprint`, `runtime_identity`, `toolchain_identity`, `revoked`
- **WorkerHeartbeat** — process-lifetime executor identity, container incarnation, state and heartbeat time

## Verification status

- Backend unit/service/API tests and the coverage floor are wired into CI. Recovery inspection, finalization, reconciliation, queue recovery, registry verification and notification suites are part of the backend suite. Real daemon fixtures are separately opt-in with `--run-container-integration`; their presence does not establish browser or production acceptance.
- Frontend CI runs Vitest plus the required Vite-only mocked-browser, disposable real-stack and workspace/IDE gateway browser jobs; the combined provenance/recovery/recreation acceptance run is enabled with `E2E_COMBINED=1`. Image publishing depends on those checks.
- The combined provenance/offline-recovery/queued-recreation scenario is part of the local disposable-stack suite. A real-stack worker-crash exercise remains a release-verification gap; the recovery paths use proof-backed inspection rather than time-based takeover.
- Load-test tooling exists; its presence does not establish current production capacity.

## Capability review

| Capability | Status | Implemented evidence | Remaining scope |
| --- | --- | --- | --- |
| Environment image build/publish | Complete | `.github/workflows/ci.yml`, `scripts/ci-version.sh`, strict base-image pinning and weekly digest review | Digest updates remain reviewed manual changes after drift review; scientific image validation is owned by the separate environments repository |
| Reproducible environments | Complete | Approved immutable revisions/caches and verified generations; registry policy, exact platform-digest proof, optional digest pulls, portable fingerprints, sanitized export, recreation APIs/UI and combined real-runtime acceptance | Operator registry credentials/allowlist and preserved local-only artifacts; remote CI execution of the combined suite |
| Database backup/restore | Complete | `scripts/manage.d/backup.sh`, `restore.sh`, `db-migrate.sh`; pre-migration snapshots; backend schema guard | Automated recovery drills and broader disaster-recovery policy |
| User volume backup/restore | Complete | Owner-scoped offline private-volume admission/API/tasks/UI, bounded helper capture/restore, retention, restore pins, writer exclusion and proof-backed reconciliation (`volume_backup_service.py`, `operation_reconciler.py`, `services/volume-helper/`); combined real-stack restore and corrupt-artifact drill | Remote CI execution and operator-managed off-host storage policy |
| Resource queue experience | Complete | Typed 202 acceptance, atomic API/worker admission, owner queue UI/pending cancellation, read-only admin queue view, `starting`-request mapping with orphan proof, GPU-aware waiting and rotating bounded dispatch | Remote CI execution and a real-stack queue-crash exercise |
| Batch scientific jobs | Future | Existing schedules support server start/stop/restart; Celery runs platform tasks | User command submissions, job records, exit status, logs, artifacts, retries, and parameter sweeps |
| Workload secrets | Future | Platform signing keys, OAuth token encryption, and template environment variables already exist | Scoped credential storage, authorization, redaction, and workload injection; template variables are ordinary JSON, not a secret store |
| Deployment automation | Partial | Tagged pulls, explicit restart workflow, migration snapshots, schema guard; rollback via pinned image plus snapshot restore | Automated health verification and traffic cutover; zero-downtime deployment is not implemented |
| Browser end-to-end tests | Partial | `frontend/e2e/`, dual-mode Playwright config, `scripts/ci/e2e-stack.sh`, required unit/mocked/external/workspace CI jobs and combined acceptance suite | Flake observation and combined acceptance execution on remote CI |
| Independent penetration assessment | Future | Internal findings, remediation records, security regression tests, and scan workflow exist | External assessment and retest before public launch |

## Current priorities

Queue reliability, reproducible environments, private offline volume recovery, registry verification and frontend test CI are implemented. Remaining work is verification, operations and the deferred capabilities below.

1. **Exercise recovery operations (In Progress)** — Run worker-crash and helper-interruption drills against a disposable stack, including admin reconcile and `./nukelabctl doctor`.
2. **Operate registry verification (In Progress)** — Configure registry credentials/allowlists, verify revisions, and retain exact-digest artifacts needed for `preload_only` deployments.
3. **Data recovery drills (In Progress)** — Verify database restore and private-volume recovery in an isolated environment, including the 2.3.0 rollback path with a pinned image and snapshot stamp.
4. **Batch jobs** — Add a minimal command-based job lifecycle, then parameter sweeps after single jobs are reliable.
5. **Scoped workload secrets** — Separate credentials from ordinary template configuration; choose the storage/integration approach during design.
6. **Public-launch readiness** — Independent penetration assessment and a verified deployment/recovery procedure.

## Deferred goals

- **Deferred:** Kubernetes migration (Helm, HPA, PVCs, Network Policies, Pod Security Standards)
- **Deferred:** Blue-green traffic cutover and automatic rollback; tagged-image deployment, snapshot restore and the schema guard are already implemented
- **Deferred:** Marketplace / plugin system
- **Deferred:** Vault / sealed-secrets integration; workload secret requirements should be established before choosing an integration

Pursue Kubernetes only after saturating a single large server (32+ cores, 128GB+ RAM) and proving distribution is required.

## Decision log

See [DECISION-LOG.md](DECISION-LOG.md).
