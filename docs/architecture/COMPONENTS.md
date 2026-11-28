# NukeLab Component Responsibilities

This document describes the major runtime components, their responsibilities, and how they interact.

## Component inventory

| Component | Technology | Primary responsibility |
|---|---|---|
| Reverse proxy | Traefik v3 | Dynamic routing, TLS termination, WebSocket proxying, rate limiting |
| Frontend | Vite + React 19 SPA | Dashboard, user portal, real-time monitoring UI |
| Backend API | FastAPI (Python 3.13) | Auth, user/server/environment/plan management, Docker orchestration, metrics |
| Container runtime driver | `ContainerDriver` ABC + `DockerDriver` (`aiodocker`) | Low-level container operations: create, start, stop, delete, logs, stats; Docker covers Podman-compatible engines |
| Server spawner | `ServerSpawner` | High-level server lifecycle coordination: volumes, images, labels, readiness |
| Database | PostgreSQL 17 | Relational data, audit logs, metrics history with partitioning |
| Cache / queue | Redis | Token denylist/revocation state, pub/sub, Celery broker, response cache, rate limits |
| Background workers | Celery + Celery Beat | Billing, cleanup, scheduled tasks, notifications, maintenance windows |
| User environments | NukeIDE (nginx + Theia) | Per-user interactive development environment with JWT proxy |
| Auth sidecar | Go service on `127.0.0.1:8081` | Validates short-lived RS256 server tokens locally for nginx `auth_request` |
| Volume recovery helper | Trusted Python helper container | Offline private-volume capture/restore with bounded archive validation |
| Observability | Prometheus, Grafana, Alertmanager, Jaeger, OTel | Metrics, dashboards, alerts, distributed traces |

## Interaction matrix

```
Browser
  |
  +---> Traefik ---> Frontend SPA (static files)
  |
  +---> Traefik ---> FastAPI ---> PostgreSQL
  |                   |    |
  |                   |    +---> Redis
  |                   |    |
  |                   |    +---> Celery workers
  |                   |
  |                   +---> Docker/Podman daemon
  |                          |
  |                          +---> ContainerDriver / ServerSpawner
  |
  +---> Traefik ---> NukeIDE container ---> nginx auth sidecar ---> Theia
```

## Per-component responsibilities

### Traefik

- Routes `/*` to the frontend container
- Routes `/api/*` and `/ws` to the FastAPI backend
- Discovers and routes `/user/{username}/{server_name}` to spawned user containers via Docker labels
- Terminates TLS (when configured)
- Applies rate limits and security headers

### Frontend (Vite + React 19 SPA)

- Provides the admin dashboard and user portal
- Uses TanStack Router for type-safe routing
- Uses TanStack Query for server state, polling, and caching
- Subscribes to `/ws` for real-time server status and metrics events
- Built as static files; requires no Node.js runtime in production

### FastAPI backend

- Exposes REST endpoints under `/api/*`
- Validates JWT access tokens signed with EdDSA (Ed25519)
- Enforces RBAC through role and permission checks
- Handles server spawn/start/stop/restart/delete requests
- Owns durable queue admission, fenced lifecycle reservations, saved launch provenance, single-run batch-job admission/execution, and private-volume recovery workflows
- Manages users, environments, plans, credits, quotas, workspaces, volumes, and notifications
- Writes audit logs and request metrics
- Exposes Prometheus metrics at `/api/metrics` when enabled
- Implements graceful shutdown via `ShutdownCoordinator`

### Container runtime driver

Locations: `backend/app/container/driver.py`, `docker_driver.py`,
`factory.py`. `client.py` is a backward-compatibility shim, not the runtime
abstraction.

Responsibilities:

- Connect to the Docker/Podman socket through `aiodocker`
- Pull images
- Create containers with cgroup limits, volume mounts, security options, and Traefik labels
- Start, stop, and delete containers
- Wait for container readiness via HTTP health checks
- Stream and fetch container logs
- Collect container stats for metrics
- Manage lxcfs mounts and CPU visibility helpers
- Keep runtime failures explicit; stop/delete paths never report false success

### ServerSpawner

Location: `backend/app/container/spawner.py`

Responsibilities:

- Coordinate server creation from environment templates and resource plans
- Ensure persistent volumes exist before spawning
- Translate plans into Docker resource limits
- Generate container names and external URLs
- Attach Traefik routing labels
- Handle start/stop/delete lifecycle transitions and cleanup

### Queue, provenance, batch-job and recovery services

Locations: `backend/app/services/server_queue_service.py`,
`server_queue_dispatch_service.py`, `server_launch_service.py`,
`server_launch_validation.py`, `server_lifecycle_service.py`,
`server_provenance_service.py`, `server_recreation_service.py`,
`operation_reconciliation.py`, `operation_finalizer.py`,
`operation_reconciler.py`, `recovery_metrics.py`,
`recovery_notifications.py`, `volume_operation_service.py`,
`volume_backup_service.py`, `volume_recovery_runtime.py`,
`registry_artifact_service.py`, `environment_revision_admin_service.py`,
`batch_job_service.py`, `batch_job_admission_service.py`,
`batch_job_dispatch_service.py`, `batch_job_runtime.py`,
`batch_job_monitor.py`, `batch_job_finalizer.py`,
`batch_job_reconciliation.py`.

Responsibilities:

- Admit owner queue requests under resource-pool limits and dispatch bounded
  batches with deterministic priority ordering; resolve `starting` requests
  from their launch operation and proved runtime absence.
- Persist launch and lifecycle intent before runtime I/O, fence stale
  generations, and retain reservations for uncertain outcomes.
- Inspect runtime/artifact evidence read-only, finalize only proof-backed
  terminal outcomes, and reconcile bounded batches on a fixed cadence without
  TTL takeover.
- Record the verified launch revision and sanitized manifest, validate
  recreation/import against current authorization and catalog state, and
  verify registry digests/platform identity for admin-approved revisions.
- Capture and restore private volume archives through the trusted helper with
  storage budgets, retention pins and writer exclusion.
- Admit one noninteractive batch job against the same resource pools and an
  exclusive `job_writer` volume guard, run it in a hardened no-network
  container, and monitor/recover it without a second create or TTL takeover.
- Publish bounded recovery metrics and deduplicated owner notifications.

### Volume recovery helper

Location: `services/volume-helper/helper.py`.

Responsibilities:

- Run as a hardened, non-root helper with no host capabilities.
- Perform bounded archive validation and capture/restore only after the backend
  authorizes the operation and excludes writers.
- Restore into fresh volumes without overwriting source data or exposing source
  volume identifiers.

### PostgreSQL

Responsibilities:

- Store relational application data
- Store immutable audit logs
- Store time-series metrics history in partitioned tables (`activity_logs`, `server_metrics`, `request_metrics`)
- Support asyncpg/SQLAlchemy 2 queries from the backend

### Redis

Responsibilities:

- Session and token denylist storage
- Celery broker and result backend
- Pub/sub for real-time WebSocket message distribution
- Response caching for frequently read endpoints
- Rate limit counters (optional)

### Celery

Responsibilities:

- Debit NUKE credits for running servers
- Process scheduled server start/stop actions
- Send notifications (in-app, email, WebSocket)
- Execute maintenance window enable/disable
- Dispatch durable queue batches and reconcile expired or uncertain launches
- Dispatch, monitor and recover single-run batch jobs and retry bounded cleanup
- Run periodic cleanup, recovery retention and health tasks

### NukeIDE container

Responsibilities:

- Provide an interactive IDE (Theia) per user server
- Run nginx on port 8080 and validate server-scoped tokens through the local Go
  auth sidecar on port 8081
- Enforce that only the owning user (or a role with `servers:access_others`) can
  access the IDE
- Report container health to the backend

## Deployment overlays

Optional compose overlays extend the core stack:

| Overlay file | Adds |
|---|---|
| `compose.monitoring.yml` | Prometheus, Grafana and exporters |
| `compose.alertmanager.yml` | Alertmanager and its Traefik route |
| `compose.pgbouncer.yml` | PgBouncer connection pooler |
| `compose.monitoring-pgbouncer.yml` | PgBouncer metrics exporter |
| `compose.tracing.yml` | OpenTelemetry collector and Jaeger |
| `compose.loadtest.yml` | Load testing tooling |

See [MONITORING.md](MONITORING.md) for observability details, [BATCH-JOBS.md](BATCH-JOBS.md) for single-run batch execution, and [operations/PRODUCTION-DEPLOYMENT.md](../operations/PRODUCTION-DEPLOYMENT.md) for deployment guidance.
